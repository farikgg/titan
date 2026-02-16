import asyncio, logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.db.models.offer_model import OfferStatus
from src.worker.celery_app import app
from src.db.models.price_model import EmailProcessing
from src.services.price_service import PriceService
from src.services.skf_service import SKFService
from src.db.initialize import async_session
from src.services.lock_service import lock_service
from src.app.config import settings
from src.services.fuchs_pipeline import process_fuchs_message
from src.integrations.azure.outlook_client import OutlookClient
from src.core.graph_auth import GraphAuth

logger = logging.getLogger(__name__)


def run_async(coro):
    """
    Безопасный запуск async-кода из Celery.
    Не закрывает event loop, если он уже есть.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Celery / retry / weird env
        return asyncio.run_coroutine_threadsafe(coro, loop).result()
    else:
        return asyncio.run(coro)



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
            client = OutlookClient(auth)

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


SKF_ARTICULS = ["278661", "644-46364-8", "085734"]
@app.task(name="src.worker.tasks.sync_skf_prices")
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
            acquired = await lock_service.acquire_lock(lock_key, 6)  # нужно поменять на 600 на проде
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


@app.task(name="src.worker.tasks.sync_skf_single")
def sync_skf_single(sku: str):
    """
    Обновляет цены для одного товара SKF
    """
    async def _inner():
        skf_service = SKFService()
        price_service = PriceService()

        lock_key = f"skf:{sku}"
        acquired = await lock_service.acquire_lock(lock_key, expire=6) # поменять на проде на 600
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
    """
    async def _inner():
        from src.core.bitrix import get_bitrix_client
        from src.services.bitrix_service import BitrixService

        bx = get_bitrix_client()
        bitrix_service = BitrixService(bx)

        deal = await bitrix_service.get_deal(deal_id)
        if not deal:
            logger.warning(f"Сделка {deal_id} не найдена")
            return

        stage_id = deal.get("STAGE_ID")

        if stage_id != settings.BITRIX_STAGES.DEAL_PAID:
            return

        # запускаем PDF генерацию
        generate_offer_pdf_task.delay(deal_id, stage_id, settings.TELEGRAM_CHAT_ID)

    run_async(_inner())


async def _generate_offer_pdf(offer_id: int, chat_id: int):

    from src.services.pdf_service import PdfService
    from src.db.initialize import async_session
    from src.db.models.offer_model import OfferModel
    from src.db.models.audit_log import AuditLog
    from src.services.telegram_service import TelegramService

    tg = TelegramService()
    pdf_service = PdfService()

    async with async_session() as session:

        offer = await session.get(OfferModel, offer_id)

        if not offer:
            await tg.send_message(chat_id, "❌ Offer не найден")
            return

        # БЛОКИРОВКА ОТ ДУБЛЕЙ
        if offer.is_generating:
            await tg.send_message(chat_id, "⏳ PDF уже генерируется...")
            return

        offer.is_generating = True
        await session.commit()

    progress = await tg.send_message(chat_id, "🧾 Генерирую PDF...")

    try:

        async with async_session() as session:
            offer = await session.get(OfferModel, offer_id)
            await session.refresh(offer, ["items"])
            items = offer.items

            pdf_path = pdf_service.generate_offer(
                deal={
                    "id": offer.id,
                    "title": f"КП #{offer.id}",
                    "items": [
                        {
                            "name": i.name,
                            "price": float(i.price),
                            "quantity": i.quantity,
                            "total": float(i.total),
                        }
                        for i in items
                    ],
                }
            )

            offer.pdf_path = pdf_path
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

        await tg.edit_message(
            chat_id,
            progress["message_id"],
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

        await tg.edit_message(
            chat_id,
            progress["message_id"],
            "❌ Ошибка генерации"
        )

        raise

@app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    time_limit=600,
    rate_limit="5/m",
    soft_time_limit=480,
    name="src.worker.tasks.generate_pdf_task",
)
def generate_offer_pdf_task(self, offer_id: int, chat_id: int):
    return run_async(_generate_offer_pdf(offer_id, chat_id))


@app.task(name="src.worker.tasks.sync_skf_bulk")
def sync_skf_bulk(skus: list[str]):
    """
    Массовое обновление цен SKF.
    Используется из PriceService.resolve_prices
    """
    for sku in skus:
        sync_skf_single.delay(sku)
