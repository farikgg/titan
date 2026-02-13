import asyncio, logging
from pathlib import Path

from src.repositories.price_repo import PriceRepository
from src.worker.celery_app import app
from src.services.mail_parser import EmailParser
from src.services.price_service import PriceService
from src.services.skf_service import SKFService
from src.db.initialize import async_session
from src.services.lock_service import lock_service
from src.app.config import settings
from src.services.fuchs_pipeline import process_fuchs_message
from src.services.telegram_service import TelegramService

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
    name="src.worker.tasks.parse_from_fuchs",
)
def parse_from_fuchs(self):
    """
    Оркестратор парсинга писем FUCHS:
    - вытаскивает письма
    - фильтрует уже обработанные
    - отправляет в heavy ai_process
    """
    parser = EmailParser()
    repo = PriceRepository()

    async def _inner():
        messages = await parser.fetch_last_message(limit=200)

        async with async_session() as session:
            for msg in messages:
                message_id = msg.get("message_ids")
                if not message_id:
                    continue

                exists = await repo.exists_by_message_id(session, message_id)
                if exists:
                    logger.info("Письмо %s уже обработано, пропуск", message_id)
                    continue

                ai_process.delay(msg)

    run_async(_inner())
    return "FUCHS parsing dispatched"


@app.task(
    autoretry_for=(Exception,),
    retry_backoff=True,
    bind=True,
    time_limit=600,
    soft_time_limit=480,
    name="src.worker.tasks.ai_process",
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
    retry_exceptions=(TimeoutError, ConnectionError),
)
def ai_process(self, msg_dict):
    return run_async(process_fuchs_message(msg_dict))


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
        generate_pdf_task.delay(deal_id, stage_id, settings.TELEGRAM_CHAT_ID)

    run_async(_inner())


async def generate_pdf(deal_id: int, stage_id: str, chat_id: int):
    """
    Генерация PDF коммерческого предложения.
    """
    from src.core.bitrix import get_bitrix_client
    from src.services.bitrix_service import BitrixService
    from src.services.price_service import PriceService
    from src.services.pdf_service import PdfService
    from src.db.models.pdf_generation import PdfGeneration
    from sqlalchemy import select
    from src.db.initialize import async_session

    bx = get_bitrix_client()
    bitrix_service = BitrixService(bx)
    price_service = PriceService()
    pdf_service = PdfService()

    deal = await bitrix_service.get_deal(deal_id)
    if not deal:
        logger.error(f"Сделка: {deal_id} не найдена для PDF файла")
        return None

    async with async_session() as session:
        exists = await session.scalar(
            select(PdfGeneration.id).where(
                PdfGeneration.deal_id == deal_id,
                PdfGeneration.stage_id == stage_id,
            )
        )
        if exists:
            logger.info(f"PDF файл уже был создан для сделки: {deal_id}")
            return "PDF файл уже был создан"

        session.add(PdfGeneration(deal_id=deal_id, stage_id=stage_id))
        await session.commit()

    products = await bitrix_service.get_deal_products(deal_id)

    async with async_session() as session:
        skus = [p["PRODUCT_ID"] for p in products]

        resolved_prices = await price_service.resolve_prices(
            db=session,
            skus=skus,
            source="fuchs",
        )

    pdf_path = pdf_service.generate_offer(
        deal={
            "id": deal_id,
            "title": deal["TITLE"],
            "items": resolved_prices,
            "currency": deal["CURRENCY_ID"],
        }
    )
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        logger.error("PDF не найден")
        return None

    tg = TelegramService()

    await tg.send_message(
        chat_id=chat_id,
        text = f"PDF создан\n"
               f"Сделка: {deal_id}\n"
               f"Stage: {stage_id}"
    )

    await tg.send_document(
        chat_id=chat_id,
        file_path=pdf_path,
        caption=f"Коммерческое предложение по сделке {deal_id}",
    )

    await tg.send_message(chat_id, f"🔍 Получаю данные сделки {deal_id}...")
    await tg.send_message(chat_id, "📦 Получаю товары...")
    await tg.send_message(chat_id, "💰 Рассчитываю цены...")
    await tg.send_message(chat_id, "🧾 Генерирую PDF...")
    await tg.send_message(chat_id, "✅ PDF успешно создан")
    await tg.send_message(chat_id, "❌ Ошибка при создании PDF")

    logger.info(f"Создался PDF файл для сделки: {deal_id}, где он находиться: {pdf_path}")
    return pdf_path


@app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    time_limit=600,
    soft_time_limit=480,
    name="src.worker.tasks.generate_pdf_task",
)
def generate_pdf_task(self, deal_id: int, stage_id: str, chat_id: int):
    return run_async(generate_pdf(deal_id, stage_id, chat_id))


@app.task(name="src.worker.tasks.sync_skf_bulk")
def sync_skf_bulk(skus: list[str]):
    """
    Массовое обновление цен SKF.
    Используется из PriceService.resolve_prices
    """
    for sku in skus:
        sync_skf_single.delay(sku)
