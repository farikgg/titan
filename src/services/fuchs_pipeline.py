from src.repositories.price_repo import PriceRepository
from src.services.price_service import PriceService, PriceCreate
from src.services.fuchs_parser import FuchsAIParser
from src.services.excel_parser import FuchsExcelParser
from src.db.initialize import async_session
import logging

logger = logging.getLogger(__name__)


async def process_fuchs_message(msg_dict: dict) -> str:
    ai_parser = FuchsAIParser()
    excel_parser = FuchsExcelParser()
    repo = PriceRepository()
    price_service = PriceService()

    raw_message_id = msg_dict.get("message_ids")

    if isinstance(raw_message_id, list):
        message_id = raw_message_id[0]
    else:
        message_id = raw_message_id

    async with async_session() as session:
        exists = await repo.exists_by_message_id(
            session,
            message_id,
        )
        if exists:
            return "Already processed"

    if not ai_parser.is_not_spam(msg_dict["subject"], msg_dict["body"]):
        return "Spam"

    attachments = msg_dict.get("attachments", [])
    items: list[PriceCreate] = []

    # 1️⃣ Excel
    for att in attachments:
        if att["name"].lower().endswith((".xls", ".xlsx")):
            items = excel_parser.parse(att["content"])
            if items:
                break

    # 2️⃣ AI fallback
    if not items:
        attachment_text = ai_parser.extract_text_from_attachments(attachments)
        items = await ai_parser.parse_to_objects(
            msg_dict["body"],
            attachment_text,
        )

    if not items:
        return "No data"

    valid_items = [item for item in items if item.price is not None]

    if not valid_items:
        logger.info("AI returned items without prices, skipping save")
        return "No priced data"

    async with async_session() as session:
        for item in valid_items:
            item.email_message_id = message_id
            await price_service.update_or_create(session, item)
        await session.commit()

    return f"Сохранено: {len(valid_items)}"
