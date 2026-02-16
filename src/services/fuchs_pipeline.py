from src.repositories.price_repo import PriceRepository
from src.services.price_service import PriceService, PriceCreate
from src.services.fuchs_parser import FuchsAIParser
from src.services.excel_parser import FuchsExcelParser
from src.services.telegram_service import TelegramService
from src.db.initialize import async_session
from src.app.config import settings

import logging

logger = logging.getLogger(__name__)


async def process_fuchs_message(msg_dict: dict) -> str:
    ai_parser = FuchsAIParser()
    excel_parser = FuchsExcelParser()
    repo = PriceRepository()
    price_service = PriceService()
    tg = TelegramService()

    raw_message_id = msg_dict.get("message_ids")

    message_id = (
        raw_message_id[0]
        if isinstance(raw_message_id, list)
        else raw_message_id
    )

    if not message_id:
        return "No message id"

    # -------- SPAM CHECK --------
    if not ai_parser.is_not_spam(
        msg_dict.get("subject", ""),
        msg_dict.get("body", ""),
    ):
        return "Spam"

    attachments = msg_dict.get("attachments", [])
    items: list[PriceCreate] = []

    # -------- 1. Excel --------
    for att in attachments:
        if att["name"].lower().endswith((".xls", ".xlsx")):
            items = excel_parser.parse(att["content"])
            if items:
                break

    # -------- 2. AI fallback --------
    if not items:
        attachment_text = ai_parser.extract_text_from_attachments(attachments)
        items = await ai_parser.parse_to_objects(
            msg_dict.get("body", ""),
            attachment_text,
        )

    if not items:
        return "No data"

    valid_items = [item for item in items if item.price is not None]

    if not valid_items:
        logger.info("AI returned items without prices, skipping save")
        return "No priced data"

    # -------- DB SAVE (atomic) --------
    async with async_session() as session:

        exists = await repo.exists_by_message_id(session, message_id)
        if exists:
            return "Already processed"

        for item in valid_items:
            item.email_message_id = message_id
            await price_service.update_or_create(session, item)

        await session.commit()

    # -------- TELEGRAM AFTER COMMIT --------
    await tg.send_message(
        chat_id=settings.TELEGRAM_CHAT_ID,
        text=(
            f"Обработано письмо FUCHS\n"
            f"Message ID: {message_id}\n"
            f"Позиций: {len(valid_items)}"
        ),
    )

    return f"Saved: {len(valid_items)}"

