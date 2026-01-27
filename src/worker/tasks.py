import asyncio, logging

from src.repositories.price_repo import PriceRepository
from src.worker.celery_app import app
from src.services.fuchs_parser import FuchsAIParser
from src.services.mail_parser import EmailParser
from src.services.price_service import PriceService
from src.services.skf_service import SKFService
from src.db.initialize import async_session

logger = logging.getLogger(__name__)


ai_parser = FuchsAIParser()
price_service = PriceService()
skf_service = SKFService()
repo = PriceRepository() # доступ к БД
parser = EmailParser()


def run_async(coro):
    return asyncio.run(coro)


@app.task(bind=True,
          max_retries=3,
          name="src.worker.tasks.parse_from_fuchs")
def parse_from_fuchs(self):
    """
    Основной таск для парсинга писем
    """
    # парсим письма за последние 3 месяца, лимит надо уточнить у заказчиков, сколько писем приходит за 3 месяца
    messages = run_async(parser.fetch_last_message(500))

    async def filter_and_dispatch():
        async with async_session() as session:
            for msg in messages:
                # ПРОВЕРКА: Если письмо уже обрабатывали — пропускаем
                if await repo.exists_by_message_id(session, msg['message_id']):
                    logger.info(f"Письмо {msg['message_ids']} уже есть в базе. Пропуск.")
                    continue

                # Если новое — отправляем в тяжелую очередь
                ai_process.delay(msg)

    run_async(filter_and_dispatch())


@app.task(autoretry_for=(Exception,),
          retry_backoff=True,
          bind=True,
          max_retries=5,
          # ИЗОЛЯЦИЯ: Ограничиваем время выполнения тяжелой задачи
          time_limit=600, # 10 минут максимум на всё
          soft_time_limit=480,  # через 8 минут Celery получит сигнал о завершении
          name="src.worker.tasks.ai_process")
def ai_process(msg_dict):
    """
    ИИ обработка письма
    """
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
        async def save_all():
            async with async_session() as session:
                for item in validated_items:
                    await price_service.add_new_price(session, item)

        run_async(save_all())
        return f"Сохранено: {len(validated_items)} писем"

    return "Ничего не сохранено"


SKF_ARTICULS = ["278661", "644-46364-8", "085734"]
@app.task(name="src.worker.tasks.sync_skf_prices")
def sync_skf_prices_task():
    """
    Обновляет цены для списка важных артикулов SKF
    """
    for sku in SKF_ARTICULS:
        price_data = run_async(skf_service.get_price(sku))
        if price_data:
            async def save():
                async with async_session() as session:
                    await price_service.add_new_price(session, price_data)
            run_async(save())
