import asyncio, logging

from src.worker.celery_app import app
from src.services.fuchs_parser import FuchsAIParser
from src.services.mail_parser import EmailParser
from src.services.price_service import PriceService
from src.db.initialize import async_session

logger = logging.getLogger(__name__)


def run_async(coro):
    return asyncio.run(coro)


@app.task(bind=True, max_retries=3)
def parse_from_fuchs(self):
    """
    Основной таск для парсинга писем
    """
    parser = EmailParser()
    # парсим письма за последние 3 месяца, лимит надо уточнить у заказчиков, сколько писем приходит за 3 месяца
    messages = run_async(parser.fetch_last_message(500))

    logger.info(f"Найдено: {len(messages)} писем для обработки")

    for msg in messages:
        ai_process.delay(msg)


@app.task(autoretry_for=(Exception,), retry_backoff=True,  max_retries=5)
def ai_process(msg_dict):
    """
    ИИ обработка письма
    """
    ai_parser = FuchsAIParser()
    price_service = PriceService()

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
