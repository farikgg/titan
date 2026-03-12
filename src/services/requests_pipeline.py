"""
Pipeline для обработки писем из requests@... ящика.

Флоу:
1. Парсинг письма (Excel или AI)
2. Извлечение данных клиента (AI)
3. Поиск/создание компании и контакта в Bitrix
4. Создание сделки в Bitrix
5. Поиск товаров в прайсах
6. Создание корзины (Offer) для сделки
7. Уведомление менеджера
"""

from src.services.fuchs_parser import FuchsAIParser
from src.services.excel_parser import FuchsExcelParser
from src.services.telegram_service import TelegramService, get_admin_chat_ids
from src.services.deal_service import DealService
from src.services.bitrix_service import BitrixService
from src.services.offer_service import OfferService
from src.services.price_service import PriceService
from src.core.bitrix import get_bitrix_client
from src.db.initialize import async_session
from src.app.config import settings
from src.db.models.price_model import PriceModel
from sqlalchemy import select

import logging

logger = logging.getLogger(__name__)

# Bitrix user ID по умолчанию для автоматически созданных сделок
DEFAULT_ASSIGNED_BY_ID = 109


async def extract_client_info(subject: str, body: str, sender: str) -> dict:
    """
    Извлекает информацию о клиенте из письма с помощью AI.
    
    Returns:
        {
            "company_name": str | None,
            "contact_name": str | None,
            "contact_email": str | None,
            "contact_phone": str | None,
        }
    """
    ai_parser = FuchsAIParser()
    
    # Формируем промпт для LLM
    body_limited = body[:2000] if body else ""  # Ограничиваем длину
    prompt = f"""
Извлеки информацию о клиенте из следующего письма:

Тема: {subject}
Отправитель: {sender}
Текст письма:
{body_limited}

Верни JSON с полями:
- company_name: название компании (если есть)
- contact_name: ФИО контактного лица (если есть)
- contact_email: email контакта (если есть)
- contact_phone: телефон контакта (если есть)

Если информации нет, верни null для соответствующего поля.
"""

    try:
        # Используем LLM для извлечения структурированных данных
        response = await ai_parser.client.chat.completions.create(
            model=ai_parser.model,
            messages=[
                {
                    "role": "system",
                    "content": "Ты помощник для извлечения структурированной информации о клиентах из писем. Отвечай только валидным JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )

        import json
        result = json.loads(response.choices[0].message.content)
        
        return {
            "company_name": result.get("company_name"),
            "contact_name": result.get("contact_name"),
            "contact_email": result.get("contact_email") or sender,  # Fallback на отправителя
            "contact_phone": result.get("contact_phone"),
        }
    except Exception:
        logger.exception("Ошибка извлечения данных клиента через AI")
        # Fallback: используем отправителя как email
        return {
            "company_name": None,
            "contact_name": None,
            "contact_email": sender,
            "contact_phone": None,
        }


async def find_or_create_company_and_contact(
    bitrix_service: BitrixService,
    company_name: str | None,
    contact_name: str | None,
    contact_email: str | None,
    contact_phone: str | None,
) -> tuple[int | None, int | None]:
    """
    Ищет или создаёт компанию и контакт в Bitrix24.
    
    Returns:
        (company_id, contact_id) или (None, None) если не удалось
    """
    company_id = None
    contact_id = None

    # Поиск компании
    if company_name:
        companies = await bitrix_service.search_companies(query=company_name, limit=5)
        if companies:
            # Берём первую найденную
            company_id = int(companies[0].get("ID"))
            logger.info("Найдена компания в Bitrix: id=%s, name=%s", company_id, company_name)
        # TODO: Если не найдена - можно создать, но пока пропускаем

    # Поиск контакта
    if contact_name or contact_email:
        query = contact_name or contact_email or ""
        contacts = await bitrix_service.search_contacts(
            query=query,
            company_id=company_id,
            limit=5,
        )
        if contacts:
            contact_id = int(contacts[0].get("ID"))
            logger.info("Найден контакт в Bitrix: id=%s", contact_id)
        # TODO: Если не найден - можно создать, но пока пропускаем

    return company_id, contact_id


async def find_items_in_prices(
    db_session,
    parsed_items: list[dict],
) -> list[dict]:
    """
    Ищет товары из письма в прайсах (prices таблица).
    
    Args:
        db_session: SQLAlchemy session
        parsed_items: список товаров из парсера [{"art": "...", "name": "...", "quantity": 1}]
    
    Returns:
        Список товаров с флагом "found": [{"art": "...", "name": "...", "price": 100.0, "quantity": 1, "found": True/False}]
    """
    result_items = []

    for item in parsed_items:
        art = item.get("art") or item.get("sku", "")
        name = item.get("name", "")
        quantity = int(item.get("quantity", 1))

        if not art:
            # Если артикула нет - помечаем как не найден
            result_items.append({
                "art": "",
                "sku": "",
                "name": name or "Товар без артикула",
                "price": 0.0,
                "quantity": quantity,
                "currency": "KZT",
                "found": False,
            })
            continue

        # Ищем в прайсах
        price_obj = await db_session.scalar(
            select(PriceModel).where(PriceModel.art == art)
        )

        if price_obj:
            # Товар найден
            result_items.append({
                "art": art,
                "sku": art,
                "name": price_obj.name,
                "price": float(price_obj.price),
                "quantity": quantity,
                "currency": price_obj.currency or "KZT",
                "found": True,
            })
        else:
            # Товар не найден - оставляем с исходными данными
            result_items.append({
                "art": art,
                "sku": art,
                "name": name or f"Товар {art}",
                "price": float(item.get("price", 0)),
                "quantity": quantity,
                "currency": item.get("currency", "KZT"),
                "found": False,
            })

    return result_items


async def process_requests_message(msg_dict: dict) -> str:
    """
    Обрабатывает письмо из requests@... ящика.
    
    Флоу:
    1. Парсинг товаров (Excel или AI)
    2. Извлечение данных клиента (AI)
    3. Поиск/создание компании и контакта в Bitrix
    4. Создание сделки в Bitrix
    5. Поиск товаров в прайсах
    6. Создание корзины (Offer) для сделки
    7. Уведомление менеджера
    """
    ai_parser = FuchsAIParser()
    excel_parser = FuchsExcelParser()
    tg = TelegramService()

    raw_message_id = msg_dict.get("message_ids")
    message_id = (
        raw_message_id[0]
        if isinstance(raw_message_id, list)
        else raw_message_id
    )

    if not message_id:
        return "No message id"

    subject = msg_dict.get("subject", "")
    body = msg_dict.get("body", "") or msg_dict.get("bodyPreview", "")
    sender = msg_dict.get("from", "") or msg_dict.get("sender", {}).get("emailAddress", {}).get("address", "")

    # -------- SPAM CHECK --------
    if not ai_parser.is_not_spam(subject, body):
        return "Spam"

    attachments = msg_dict.get("attachments", [])
    items: list = []

    # -------- 1. ПАРСИНГ ТОВАРОВ: Excel --------
    for att in attachments:
        if att["name"].lower().endswith((".xls", ".xlsx")):
            items = excel_parser.parse(att["content"])
            if items:
                break

    # -------- 2. ПАРСИНГ ТОВАРОВ: AI fallback --------
    if not items:
        attachment_text = ai_parser.extract_text_from_attachments(attachments)
        items = await ai_parser.parse_to_objects(body, attachment_text)

    if not items:
        return "No data"

    # Конвертируем в словари для дальнейшей обработки
    parsed_items = [
        {
            "art": getattr(item, "art", "") or "",
            "name": getattr(item, "name", "") or "",
            "price": float(getattr(item, "price", 0)) or 0,
            "currency": getattr(item, "currency", "KZT") or "KZT",
            "quantity": int(getattr(item, "quantity", 1)) or 1,
        }
        for item in items
    ]

    # -------- 3. ИЗВЛЕЧЕНИЕ ДАННЫХ КЛИЕНТА (AI) --------
    client_info = await extract_client_info(subject, body, sender)
    company_name = client_info.get("company_name")
    contact_name = client_info.get("contact_name")
    contact_email = client_info.get("contact_email")
    contact_phone = client_info.get("contact_phone")

    # -------- 4. ПОИСК/СОЗДАНИЕ КОМПАНИИ И КОНТАКТА В BITRIX --------
    bx = get_bitrix_client()
    bitrix_service = BitrixService(bx)
    deal_service = DealService(bitrix_service)

    company_id, contact_id = await find_or_create_company_and_contact(
        bitrix_service,
        company_name,
        contact_name,
        contact_email,
        contact_phone,
    )

    # -------- 5. СОЗДАНИЕ СДЕЛКИ В BITRIX24 --------
    deal_id = None
    try:
        deal_id = await deal_service.create_deal_from_email(
            subject=subject,
            sender=sender,
            assigned_by_id=DEFAULT_ASSIGNED_BY_ID,
            parsed_items=[],  # Пока без товаров, добавим в корзину
            message_id=message_id,
        )

        if company_id:
            await bitrix_service.update_deal(deal_id, {"COMPANY_ID": company_id})
        if contact_id:
            await bitrix_service.update_deal(deal_id, {"CONTACT_ID": contact_id})

    except Exception:
        logger.exception("Ошибка создания сделки в Bitrix24 из письма requests@...")
        return f"Error creating deal"

    if not deal_id:
        return "Failed to create deal"

    # -------- 6. ПОИСК ТОВАРОВ В ПРАЙСАХ И СОЗДАНИЕ КОРЗИНЫ --------
    async with async_session() as db_session:
        # Ищем товары в прайсах
        items_with_status = await find_items_in_prices(db_session, parsed_items)

        # Создаём корзину для сделки
        offer_service = OfferService(db_session)
        currency = items_with_status[0].get("currency", "KZT") if items_with_status else "KZT"

        try:
            offer = await offer_service.create_offer_for_deal(
                deal_id=deal_id,
                bitrix_user_id=DEFAULT_ASSIGNED_BY_ID,
                items=items_with_status,
                currency=currency,
            )
            logger.info(
                "Создана корзина offer_id=%s для сделки deal_id=%s, товаров: %d",
                offer.id,
                deal_id,
                len(items_with_status),
            )
        except Exception:
            logger.exception("Ошибка создания корзины для сделки deal_id=%s", deal_id)
            # Продолжаем, даже если корзина не создана

    # -------- 7. TELEGRAM NOTIFICATION --------
    found_count = sum(1 for item in items_with_status if item.get("found"))
    not_found_count = len(items_with_status) - found_count

    deal_text = f"🏢 ID сделки в Битрикс24: #{deal_id}"
    if company_name:
        deal_text += f"\n🏢 Компания: {company_name}"

    text = (
        "📧 Обработано письмо из requests@...\n"
        f"Тема: {subject}\n"
        f"От: {sender}\n"
        f"Товаров спарсено: {len(items_with_status)}\n"
        f"✅ Найдено в прайсах: {found_count}\n"
        f"❌ Не найдено: {not_found_count}\n"
        f"{deal_text}"
    )

    # Шлём уведомление всем админам
    for chat_id in get_admin_chat_ids():
        await tg.send_message(chat_id=chat_id, text=text)

    return f"Deal: {deal_id}, Items: {len(items_with_status)}, Found: {found_count}, Not found: {not_found_count}"
