import asyncio, logging, httpx
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.worker.celery_app import app
from src.db.models.price_model import EmailProcessing
from src.db.models.offer_model import OfferStatus
from src.services.price_service import PriceService
from src.services.skf_service import SKFService
from src.db.initialize import async_session
from src.services.lock_service import lock_service
from src.app.config import settings
from src.services.fuchs_pipeline import process_fuchs_message
from src.services.requests_pipeline import process_requests_message
from src.integrations.azure.outlook_client import OutlookClient
from src.core.graph_auth import GraphAuth
from src.services.telegram_service import TelegramService, get_admin_chat_ids
from src.services.fuchs_price_report_service import FuchsPriceReportService

logger = logging.getLogger(__name__)

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

def run_async(coro):
    return loop.run_until_complete(coro)


@app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=5,
    name="src.worker.tasks.parse_from_fuchs",
)
def parse_from_fuchs(self):

    async def _inner():
        lock_key = "fuchs:parse"

        acquired = await lock_service.acquire_lock(lock_key, 600)
        if not acquired:
            return

        try:
            auth = GraphAuth()
            # Используем папку FUCHS из настроек (по умолчанию "Inbox")
            folder_name = settings.FUCHS_FOLDER or "Inbox"
            mailbox = settings.EMAIL_USER or "testAI@tpgt-titan.com"
            client = OutlookClient(auth, mailbox=mailbox, folder_name=folder_name)

            messages = await client.fetch_last_messages(limit=50)

            async with async_session() as session:
                for msg in messages:
                    message_id = msg.get("id")
                    if not message_id:
                        continue

                    try:
                        session.add(
                            EmailProcessing(
                                message_id=message_id,
                                status="NEW"
                            )
                        )
                        await session.commit()

                    except IntegrityError:
                        await session.rollback()
                        continue

                    attachments = OutlookClient.parse_attachments(
                        msg.get("attachments")
                    )

                    ai_process.delay({
                        "message_ids": message_id,
                        "subject": msg.get("subject"),
                        "body": msg.get("bodyPreview", ""),
                        "receivedDateTime": msg.get("receivedDateTime"),
                        "attachments": attachments,
                    })
        finally:
            await lock_service.release_lock(lock_key)

    return run_async(_inner())


@app.task(
    autoretry_for=(Exception,),
    retry_backoff=True,
    bind=True,
    time_limit=600,
    soft_time_limit=480,
    rate_limit="5/m",
    name="src.worker.tasks.ai_process",
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
    retry_exceptions=(TimeoutError, ConnectionError),
)
def ai_process(self, msg_dict):
    async def _inner():
        message_id = msg_dict.get("message_ids")

        if not message_id:
            return "No message-id"

        async with async_session() as session:
            processing = await session.scalar(
                select(EmailProcessing).where(
                    EmailProcessing.message_id == message_id
                )
            )

            if not processing:
                return "Not registered"

            if processing.status == "DONE":
                return "Already done"

            if processing.status == "PROCESSING":
                return "Already processing"

            processing.status = "PROCESSING"
            await session.commit()

        try:
            result = await process_fuchs_message(msg_dict)

            async with async_session() as session:
                processing = await session.scalar(
                    select(EmailProcessing).where(
                        EmailProcessing.message_id == message_id
                    )
                )
                if processing:
                    processing.status = "DONE"
                    await session.commit()

            return result

        except Exception as e:
            async with async_session() as session:
                processing = await session.scalar(
                    select(EmailProcessing).where(
                        EmailProcessing.message_id == message_id
                    )
                )
                if processing:
                    processing.status = "FAILED"
                    await session.commit()
            raise e

    return run_async(_inner())


@app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=5,
    name="src.worker.tasks.parse_from_requests",
)
def parse_from_requests(self):
    """
    Периодическая задача для чтения писем из requests@... ящика.
    Создаёт сделки в Bitrix и корзины (Offer) для них.
    """
    async def _inner():
        lock_key = "requests:parse"

        acquired = await lock_service.acquire_lock(lock_key, 600)
        if not acquired:
            return

        try:
            auth = GraphAuth()
            # Используем папку Requests из настроек (будет создана автоматически если не существует)
            folder_name = settings.REQUESTS_FOLDER or "Requests"
            mailbox = settings.EMAIL_USER or "testAI@tpgt-titan.com"
            client = OutlookClient(auth, mailbox=mailbox, folder_name=folder_name)

            messages = await client.fetch_last_messages(limit=50)

            async with async_session() as session:
                for msg in messages:
                    message_id = msg.get("id")
                    if not message_id:
                        continue

                    try:
                        session.add(
                            EmailProcessing(
                                message_id=message_id,
                                status="NEW"
                            )
                        )
                        await session.commit()

                    except IntegrityError:
                        await session.rollback()
                        continue

                    attachments = OutlookClient.parse_attachments(
                        msg.get("attachments")
                    )

                    # Извлекаем данные письма
                    sender_info = msg.get("sender", {}).get("emailAddress", {})
                    sender_email = sender_info.get("address", "")

                    requests_process.delay({
                        "message_ids": message_id,
                        "subject": msg.get("subject", ""),
                        "body": msg.get("body", {}).get("content", ""),
                        "bodyPreview": msg.get("bodyPreview", ""),
                        "receivedDateTime": msg.get("receivedDateTime"),
                        "from": sender_email,
                        "sender": {
                            "emailAddress": sender_info,
                        },
                        "attachments": attachments,
                    })
        finally:
            await lock_service.release_lock(lock_key)

    return run_async(_inner())


@app.task(
    autoretry_for=(Exception,),
    retry_backoff=True,
    bind=True,
    time_limit=600,
    soft_time_limit=480,
    rate_limit="5/m",
    name="src.worker.tasks.requests_process",
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
    retry_exceptions=(TimeoutError, ConnectionError),
)
def requests_process(self, msg_dict):
    """
    Обрабатывает одно письмо из requests@... ящика.
    Создаёт сделку в Bitrix и корзину (Offer) для неё.
    """
    async def _inner():
        message_id = msg_dict.get("message_ids")

        if not message_id:
            return "No message-id"

        async with async_session() as session:
            processing = await session.scalar(
                select(EmailProcessing).where(
                    EmailProcessing.message_id == message_id
                )
            )

            if not processing:
                return "Not registered"

            if processing.status == "DONE":
                return "Already done"

            if processing.status == "PROCESSING":
                return "Already processing"

            processing.status = "PROCESSING"
            await session.commit()

        try:
            result = await process_requests_message(msg_dict)

            async with async_session() as session:
                processing = await session.scalar(
                    select(EmailProcessing).where(
                        EmailProcessing.message_id == message_id
                    )
                )
                if processing:
                    processing.status = "DONE"
                    await session.commit()

            return result

        except Exception as e:
            async with async_session() as session:
                processing = await session.scalar(
                    select(EmailProcessing).where(
                        EmailProcessing.message_id == message_id
                    )
                )
                if processing:
                    processing.status = "FAILED"
                    await session.commit()
            raise e

    return run_async(_inner())


@app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    name="src.worker.tasks.send_fuchs_price_expiry_report",
)
def send_fuchs_price_expiry_report(self):
    """
    Формирует Excel-отчёт по ценам FUCHS (просроченные/скоро истекают)
    и отправляет одним сообщением + файлом в админские Telegram-чаты.
    """

    async def _inner():
        tg = TelegramService()
        report_service = FuchsPriceReportService(expiring_days_threshold=7)

        async with async_session() as session:
            out_path = await report_service.build_report_xlsx(
                session, output_dir=Path("/app/media/reports")
            )

        text = (
            "📊 Отчёт по срокам действия цен FUCHS\n"
            f"Файл: {out_path.name}\n"
            "Листы: expired / expiring_soon / all"
        )

        for chat_id in get_admin_chat_ids():
            await tg.send_message(chat_id=chat_id, text=text)
            await tg.send_document(chat_id=chat_id, file_path=out_path, caption=out_path.name)

        return str(out_path)

    return run_async(_inner())


SKF_ARTICULS = ["278661", "644-46364-8", "085734"]
@app.task(
    name="src.worker.tasks.sync_skf_prices",
    autoretry_for=(httpx.ReadTimeout, httpx.HTTPStatusError),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
def sync_skf_prices_task():
    """
    Массовое обновление цен SKF (batch).
    Используется для cron / ручного запуска.
    """
    async def _inner():
        skf_service = SKFService()
        price_service = PriceService()

        for sku in SKF_ARTICULS:
            lock_key = f"skf:{sku}"
            acquired = await lock_service.acquire_lock(lock_key, 600)
            if not acquired:
                continue

            try:
                price_data = await skf_service.get_price(sku)
                if not price_data:
                    continue
                async with async_session() as session:
                    await price_service.update_or_create(session, price_data)
                    await session.commit()
            finally:
                await lock_service.release_lock(lock_key)
    run_async(_inner())


@app.task(
    name="src.worker.tasks.sync_skf_single",
    autoretry_for=(httpx.ReadTimeout, httpx.HTTPStatusError),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
def sync_skf_single(sku: str):
    """
    Обновляет цены для одного товара SKF
    """
    async def _inner():
        skf_service = SKFService()
        price_service = PriceService()

        lock_key = f"skf:{sku}"
        acquired = await lock_service.acquire_lock(lock_key, expire=600)
        if not acquired:
            return

        try:
            price_data = await skf_service.get_price(sku)
            if not price_data:
                return
            async with async_session() as session:
                await price_service.update_or_create(session, price_data)
                await session.commit()
        finally:
            await lock_service.release_lock(lock_key)
    run_async(_inner())


@app.task(name="src.worker.tasks.process_deal_update")
def process_deal_update(deal_id: int):
    """
    Обработка обновления сделки из Bitrix webhook.
    Реагирует на смену стадии в воронке Гидротех.
    """
    from src.app.config import BITRIX_STAGES

    async def _inner():
        from src.core.bitrix import get_bitrix_client
        from src.services.bitrix_service import BitrixService
        from src.services.telegram_service import TelegramService

        bx = get_bitrix_client()
        bitrix_service = BitrixService(bx)
        tg = TelegramService()

        deal = await bitrix_service.get_deal(deal_id)
        if not deal:
            logger.warning("Сделка %s не найдена", deal_id)
            return

        stage_id = deal.get("STAGE_ID")
        category_id = deal.get("CATEGORY_ID")

        # Обрабатываем только сделки из воронки Гидротех
        if str(category_id) != str(BITRIX_STAGES.CATEGORY_ID):
            return

        logger.info(
            "Webhook: сделка %s, стадия=%s, воронка=%s",
            deal_id, stage_id, category_id,
        )

        # При переходе в WON/LOSE — уведомляем всех админов
        from src.services.telegram_service import get_admin_chat_ids

        if stage_id == BITRIX_STAGES.WON:
            text = (
                f"🎉 Сделка #{deal_id} выиграна!\n"
                f"Название: {deal.get('TITLE')}\n"
                f"Сумма: {deal.get('OPPORTUNITY')} {deal.get('CURRENCY_ID')}"
            )
        elif stage_id == BITRIX_STAGES.LOSE:
            text = f"❌ Сделка #{deal_id} проиграна: {deal.get('TITLE')}"
        else:
            text = None

        if text:
            for chat_id in get_admin_chat_ids():
                await tg.send_message(chat_id=chat_id, text=text)

    run_async(_inner())


async def _generate_offer_pdf(offer_id: int, chat_id: int | None):

    from src.services.pdf_service import PdfService
    from src.db.models.offer_model import OfferModel
    from src.db.models.audit_log import AuditLog
    from src.db.models.user_model import UserModel
    from src.services.telegram_service import TelegramService
    from src.services.deal_service import DealService
    from src.services.bitrix_service import BitrixService
    from src.core.bitrix import get_bitrix_client

    tg = TelegramService()
    pdf_service = PdfService()

    async with async_session() as session:

        offer = await session.get(OfferModel, offer_id)

        if not offer:
            # Если нет chat_id (админский вызов) — просто выходим тихо
            if chat_id:
                await tg.send_message(chat_id, "❌ Offer не найден")
            return

        # БЛОКИРОВКА ОТ ДУБЛЕЙ
        if offer.is_generating:
            if chat_id:
                await tg.send_message(chat_id, "⏳ PDF уже генерируется...")
            return

        offer.is_generating = True
        await session.commit()

    progress = None
    message_id = None
    if chat_id:
        progress = await tg.send_message(chat_id, "🧾 Генерирую PDF...")
        if not progress or not progress.get("result"):
            logger.error("Не удалось получить message_id %s", progress)
            return
        message_id = progress["result"]["message_id"]

    try:

        async with async_session() as session:
            offer = await session.get(OfferModel, offer_id)
            await session.refresh(offer, ["items"])
            items = offer.items

            # Получаем информацию о менеджере (пользователе TMA)
            manager_name = ""
            manager_phone = ""
            if offer.user_id:
                user = await session.get(UserModel, offer.user_id)
                if user:
                    # username из БД (можно заменить на ФИО, если появится поле)
                    manager_name = user.username or ""
                    # Телефон менеджера пока не храним — оставляем пустым,
                    # но поле предусмотрено в PDF

            # Собираем данные для PDF, включая динамические условия КП
            pdf_path = pdf_service.generate_offer(
                deal={
                    "id": offer.id,
                    "title": f"КП #{offer.id}",
                    "currency": offer.currency,
                    # Флаг, включает ли цена НДС (управляет подписью «без НДС» в PDF)
                    "vat_enabled": getattr(offer, "vat_enabled", None),
                    # Динамические текстовые поля условий
                    "payment_terms": getattr(offer, "payment_terms", None),
                    "delivery_terms": getattr(offer, "delivery_terms", None),
                    "warranty_terms": getattr(offer, "warranty_terms", None),
                    # Информация о менеджере пока не выводится, но оставлена для совместимости
                    "manager_name": manager_name,
                    "manager_phone": manager_phone,
                    "items": [
                        {
                            "art": i.sku,
                            "name": i.name,
                            "price": float(i.price),
                            "quantity": i.quantity,
                            "total": float(i.total),
                        }
                        for i in items
                    ],
                }
            )

            offer.pdf_path = str(pdf_path)
            offer.status = OfferStatus.GENERATED
            offer.is_generating = False

            session.add(
                AuditLog(
                    actor_type="user",
                    actor_id=offer.user_id,
                    action="offer_pdf_generated",
                    payload={"offer_id": offer.id},
                )
            )

            await session.commit()

            # ── Смена стадии сделки в Bitrix24: → KP_CREATED ──
            bitrix_deal_id = offer.bitrix_deal_id
            if bitrix_deal_id:
                try:
                    bx = get_bitrix_client()
                    bitrix = BitrixService(bx)
                    deal_service = DealService(bitrix)

                    # 1) Переводим сделку в стадию «КП готово»
                    await deal_service.move_to_kp_created(int(bitrix_deal_id))
                    logger.info(
                        "Сделка %s переведена в KP_CREATED после генерации PDF",
                        bitrix_deal_id,
                    )

                    # 2) Прикрепляем PDF КП к сделке в поле «Вложить Договор и Спецификацию»
                    from pathlib import Path as _Path

                    await bitrix.attach_kp_pdf(
                        int(bitrix_deal_id),
                        _Path(pdf_path),
                    )
                except Exception:
                    logger.exception(
                        "Ошибка обработки сделки %s после генерации КП (смена стадии / прикрепление файла)",
                        bitrix_deal_id,
                    )

        # Если есть chat_id (вызов из Telegram) — шлём уведомление и документ.
        if chat_id and message_id:
            await tg.edit_message(
                chat_id,
                message_id,
                "✅ PDF готов"
            )

            await tg.send_document(
                chat_id,
                Path(pdf_path),
                caption=f"Коммерческое предложение #{offer_id}"
            )

    except Exception as e:

        async with async_session() as session:
            offer = await session.get(OfferModel, offer_id)
            offer.is_generating = False
            await session.commit()

        if chat_id and progress and progress.get("result"):
            await tg.edit_message(
                chat_id,
                progress["result"]["message_id"],
                "❌ Ошибка генерации"
            )

        raise

    finally:
        async with async_session() as session:
            offer = await session.get(OfferModel, offer_id)
            if offer:
                offer.is_generating = False
                await session.commit()

@app.task(
    bind=True,
    autoretry_for=(httpx.ReadTimeout, httpx.HTTPStatusError),
    retry_backoff=True,
    max_retries=3,
    time_limit=600,
    rate_limit="5/m",
    soft_time_limit=480,
    name="src.worker.tasks.generate_pdf_task",
)
def generate_offer_pdf_task(self, offer_id: int, chat_id: int | None = None):
    return run_async(_generate_offer_pdf(offer_id, chat_id))


@app.task(name="src.worker.tasks.sync_skf_bulk")
def sync_skf_bulk(skus: list[str]):
    """
    Массовое обновление цен SKF.
    Используется из PriceService.resolve_prices
    """
    for sku in skus:
        sync_skf_single.delay(sku)
