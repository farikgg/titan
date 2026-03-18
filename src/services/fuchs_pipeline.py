from src.repositories.price_repo import PriceRepository
from src.services.price_service import PriceService, PriceCreate
from src.services.fuchs_parser import FuchsAIParser
from src.services.excel_parser import FuchsExcelParser
from src.services.telegram_service import TelegramService, get_admin_chat_ids
from src.services.deal_service import DealService
from src.services.bitrix_service import BitrixService
from src.core.bitrix import get_bitrix_client
from src.db.initialize import async_session
from src.app.config import settings

import logging

logger = logging.getLogger(__name__)

# Bitrix user ID по умолчанию для автоматически созданных сделок.
# Позже можно привязывать к конкретному менеджеру через маршрутизацию.
DEFAULT_ASSIGNED_BY_ID = 109


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

    # -------- СОЗДАНИЕ СДЕЛКИ В BITRIX24 (воронка Гидротех) --------
    # deal_id = None
    # try:
    #     bx = get_bitrix_client()
    #     deal_service = DealService(BitrixService(bx))

    #     deal_id = await deal_service.create_deal_from_email(
    #         subject=msg_dict.get("subject", ""),
    #         sender=msg_dict.get("from", "FUCHS"),
    #         assigned_by_id=DEFAULT_ASSIGNED_BY_ID,
    #         parsed_items=[
    #             {
    #                 "art": item.art,
    #                 "name": item.name,
    #                 "price": float(item.price) if item.price else 0,
    #                 "currency": item.currency or "EUR",
    #                 "quantity": 1,
    #             }
    #             for item in valid_items
    #         ],
    #         message_id=message_id,
    #     )
    # except Exception:
    #     logger.exception("Ошибка создания сделки в Bitrix24 из письма FUCHS")

    # -------- TELEGRAM NOTIFICATION --------
    subject = msg_dict.get("subject") or "Без темы"
    items_count = len(valid_items)

    # if deal_id:
    #     deal_text = f"🏢 ID сделки в Битрикс24: #{deal_id}"
    # else:
    #     deal_text = "⚠️ Сделка в Битрикс24 не создана"
    deal_text = "ℹ️ Сделка в Bitrix24 не создавалась (обновлён только прайс)"

    text = (
        "📧 Обработано письмо FUCHS\n"
        f"Тема: {subject}\n"
        f"Товаров спарсено: {items_count}\n"
        f"{deal_text}"
    )

    # Шлём уведомление всем, чей chat_id указан в TELEGRAM_CHAT_ID (через запятую)
    for chat_id in get_admin_chat_ids():
        await tg.send_message(chat_id=chat_id, text=text)

    # return f"Saved: {len(valid_items)}, deal: {deal_id}"
    return f"Saved: {len(valid_items)}, deal: None"
