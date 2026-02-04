import asyncio, logging

from src.repositories.price_repo import PriceRepository
from src.worker.celery_app import app
from src.services.fuchs_parser import FuchsAIParser
from src.services.mail_parser import EmailParser
from src.services.price_service import PriceService
from src.services.skf_service import SKFService
from src.db.initialize import async_session
from src.services.lock_service import lock_service

logger = logging.getLogger(__name__)


def run_async(coro):
    """
    Единственная точка входа в asyncio для Celery тасков.
    НЕ вызывать изнутри async функций.
    """
    return asyncio.run(coro)


@app.task(bind=True,
          max_retries=3,
          name="src.worker.tasks.parse_from_fuchs")
def parse_from_fuchs(self):
    """
    Основной таск для парсинга писем из FUCHS
    """
    # парсим письма за последние 3 месяца, лимит надо уточнить у заказчиков, сколько писем приходит за 3 месяца
    # parser = EmailParser()
    # messages = run_async(parser.fetch_last_message(500))
    mock_messages = [{
        "message_ids": "test-id-999", # Используй то же имя, что в mail_parser
        "subject": "Актуальные цены FUCHS",
        "body": "Цена на 601072093 URETHYN CC 2-1 составляет 450.50 EUR. Также RENOLIN CLP 320 стоит 1200 EUR.",
        "attachments": []
    }]
    for msg in mock_messages:
        ai_process.delay(msg)

    # async def filter_and_dispatch():
    #     repo = PriceRepository()  # доступ к БД
    #     async with async_session() as session:
    #         for msg in messages:
    #             # ПРОВЕРКА: Если письмо уже обрабатывали — пропускаем
    #             if await repo.exists_by_message_id(session, msg['message_ids']):
    #                 logger.info(f"Письмо {msg['message_ids']} уже есть в базе. Пропуск.")
    #                 continue
    #
    #             # Если новое — отправляем в тяжелую очередь
    #             ai_process.delay(msg)

    # run_async(filter_and_dispatch())


@app.task(autoretry_for=(Exception,),
          retry_backoff=True,
          bind=True,
          max_retries=5,
          # ИЗОЛЯЦИЯ: Ограничиваем время выполнения тяжелой задачи
          time_limit=600, # 10 минут максимум на всё
          soft_time_limit=480,  # через 8 минут Celery получит сигнал о завершении
          name="src.worker.tasks.ai_process")
def ai_process(self, msg_dict):
    """
    ИИ обработка письма
    """
    ai_parser = FuchsAIParser()
    # обработка на спам
    is_valid = run_async(ai_parser.is_not_spam(msg_dict['subject'], msg_dict['body']))
    if not is_valid:
        logger.info(f"Это спам: {msg_dict['subject']}, обрабатываю след. письмо")
        return "Spam"

    # берем из письма доп. доки(pdf, sheets, images)
    attachment_text  = ""
    if msg_dict.get('attachments'):
        attachment_text = ai_parser.extract_text_from_attachments(msg_dict['attachments'])

    # парсинг через ИИ
    validated_items = run_async(ai_parser.parse_to_objects(msg_dict['body'], attachment_text))

    # сохранение в БД
    if validated_items:
        price_service = PriceService()
        async def save_all():
            async with async_session() as session:
                for item in validated_items:
                    await price_service.update_or_create(session, item)
                await session.commit()

        run_async(save_all())
        return f"Успех: сохранено {len(validated_items)} позиций товаров"

    return "Ничего не сохранено"


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
                return

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
    