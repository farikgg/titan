from src.repositories.price_repo import PriceRepository
from src.services.price_service import PriceService, PriceCreate
from src.services.fuchs_parser import FuchsAIParser
from src.services.excel_parser import FuchsExcelParser, FuchsAnalogExcelParser
from src.repositories.analog_repo import AnalogRepository
from src.services.telegram_service import TelegramService, get_admin_chat_ids
from src.services.deal_service import DealService
from src.services.bitrix_service import BitrixService
from src.core.bitrix import get_bitrix_client
from src.db.initialize import async_session
from src.app.config import settings

import logging
from datetime import datetime, timezone

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

    # Дата получения письма из Microsoft Graph (ISO 8601), например: "2026-03-18T04:08:09Z"
    received_raw = msg_dict.get("receivedDateTime")
    received_at: datetime | None = None
    if isinstance(received_raw, str) and received_raw.strip():
        try:
            # поддерживаем Z
            iso = received_raw.replace("Z", "+00:00")
            received_at = datetime.fromisoformat(iso)
            # нормализуем к naive UTC для хранения/сравнения
            if received_at.tzinfo is not None:
                received_at = received_at.astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            received_at = None

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
        extraction_result = await ai_parser.parse_to_objects(
            msg_dict.get("body", ""),
            attachment_text,
        )
        
        raw_items = extraction_result.get("items", [])
        if not isinstance(raw_items, list):
            raw_items = []

        # Fallback-дата из корневого массива dates (если у товара нет start_date)
        fallback_date: datetime | None = None
        raw_dates = extraction_result.get("dates")
        if isinstance(raw_dates, list) and raw_dates:
            try:
                fallback_date = datetime.strptime(raw_dates[0], "%Y-%m-%d")
            except (ValueError, TypeError):
                logger.warning("Невалидная дата в dates: %s", raw_dates[0])

        for ri in raw_items:
            try:
                # Парсим даты действия цены из AI-ответа
                ai_valid_from = None
                ai_valid_days = None
                raw_start = ri.get("start_date")
                raw_end = ri.get("end_date")

                if raw_start:
                    try:
                        ai_valid_from = datetime.strptime(raw_start, "%Y-%m-%d")
                    except (ValueError, TypeError):
                        logger.warning("Невалидная start_date от AI: %s", raw_start)

                # Fallback: если start_date нет, берём первую дату из корневого dates
                if not ai_valid_from and fallback_date:
                    ai_valid_from = fallback_date

                if raw_end:
                    try:
                        end_dt = datetime.strptime(raw_end, "%Y-%m-%d")
                        if ai_valid_from:
                            delta = (end_dt - ai_valid_from).days
                            if delta > 0:
                                ai_valid_days = delta
                    except (ValueError, TypeError):
                        logger.warning("Невалидная end_date от AI: %s", raw_end)

                item_data = {
                    "art": ri.get("art"),
                    "name": ri.get("name"),
                    "raw_name": ri.get("raw_name"),
                    "description": ri.get("description"),
                    "price": ri.get("price"),
                    "quantity": ri.get("quantity", 1.0),
                    "unit": ri.get("unit"),
                    "currency": ri.get("currency", "EUR"),
                    "container_size": ri.get("container_size"),
                    "container_unit": ri.get("container_unit"),
                    "source": "fuchs",
                    "source_type": "email",
                }

                if ai_valid_from:
                    item_data["valid_from"] = ai_valid_from
                if ai_valid_days:
                    item_data["valid_days"] = ai_valid_days

                items.append(PriceCreate(**item_data))
            except Exception as e:
                logger.warning(f"Ошибка маппинга товара AI: {e}")

    if not items:
        return "No data"

    valid_items = [item for item in items if item.price is not None]

    logger.info(
        "Извлечено товаров: %d, из них с ценой (valid_items): %d",
        len(items),
        len(valid_items),
    )

    if not valid_items:
        logger.info("AI returned items without prices, skipping save")
        return "No priced data"

    for i, vi in enumerate(valid_items):
        logger.info(
            "  [%d] art=%s name=%s price=%s currency=%s container=%s %s",
            i, vi.art, vi.name, vi.price, vi.currency,
            vi.container_size, vi.container_unit,
        )

    # -------- АНАЛОГИ ИЗ EXCEL --------
    analog_excel_parser = FuchsAnalogExcelParser()
    analog_repo = AnalogRepository()
    analog_pairs: list[dict] = []
    for att in attachments:
        if att["name"].lower().endswith((".xls", ".xlsx")):
            pairs = analog_excel_parser.parse(att["content"])
            if pairs:
                analog_pairs.extend(pairs)
                logger.info("Найдено аналогов в %s: %d", att["name"], len(pairs))
    if analog_pairs:
        try:
            async with async_session() as session:
                for pair in analog_pairs:
                    await analog_repo.create(
                        session,
                        source_art=pair["source_code"] or pair["source_name"],
                        source_product_name=pair["source_name"],
                        analog_art=pair["analog_art"],
                        analog_name=pair["analog_name"],
                        analog_brand=pair["analog_brand"],
                        analog_source="FUCHS",
                        confidence_level=0.85,
                        status="new",
                        email_thread_id=message_id,
                        added_from="email",
                    )
                await session.commit()
                logger.info("Сохранено аналогов: %d", len(analog_pairs))
        except Exception as e:
            logger.error("Ошибка сохранения аналогов: %s", e, exc_info=True)

    # -------- DB SAVE (atomic) --------
    try:
        async with async_session() as session:

            exists = await repo.exists_by_message_id(session, message_id)
            if exists:
                logger.info("message_id=%s уже обработан, пропускаем", message_id)
                return "Already processed"

            logger.info(
                "Начинаю сохранение %d товаров в БД (message_id=%s)",
                len(valid_items),
                message_id,
            )

            for item in valid_items:
                item.email_message_id = message_id
                # valid_from: приоритет у даты из AI (start_date), fallback — дата получения письма
                if not item.valid_from and received_at:
                    item.valid_from = received_at
                if getattr(item, "valid_days", None) is None:
                    item.valid_days = 90
                logger.info(
                    "  update_or_create: art=%s price=%s valid_from=%s valid_days=%s",
                    item.art, item.price, item.valid_from, item.valid_days,
                )
                await price_service.update_or_create(session, item)

            await session.commit()
            logger.info(
                "session.commit() выполнен успешно, сохранено %d товаров (message_id=%s)",
                len(valid_items),
                message_id,
            )
    except Exception as e:
        logger.error(
            "DB Save Error при сохранении прайсов (message_id=%s): %s",
            message_id,
            e,
            exc_info=True,
        )

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
