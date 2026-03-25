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


async def extract_client_info(
    subject: str, 
    body: str, 
    sender: str,
    to_recipients: list | None = None,
    parsed_items: list | None = None,
) -> dict:
    """
    Извлекает информацию о клиенте и менеджере из письма с помощью AI.
    
    Args:
        subject: Тема письма
        body: Текст письма
        sender: Email отправителя
        to_recipients: Список получателей (кому пишет клиент) - опционально
        parsed_items: Список товаров из письма - опционально (для контекста)
    
    Returns:
        {
            "company_name": str | None,
            "contact_name": str | None,  # Имя клиента, который запрашивает
            "contact_email": str | None,
            "contact_phone": str | None,
            "manager_name": str | None,  # Имя менеджера, кому пишет клиент
            "manager_email": str | None,  # Email менеджера
        }
    """
    ai_parser = FuchsAIParser()
    
    # Формируем информацию о получателях
    to_info = ""
    if to_recipients:
        to_emails = []
        to_names = []
        for recipient in to_recipients:
            if isinstance(recipient, dict):
                email_addr = recipient.get("emailAddress", {})
                email = email_addr.get("address", "")
                name = email_addr.get("name", "")
                if email:
                    to_emails.append(email)
                if name:
                    to_names.append(name)
            elif isinstance(recipient, str):
                to_emails.append(recipient)
        if to_emails or to_names:
            to_info = f"\nПолучатели письма (кому пишет клиент):\n"
            if to_names:
                to_info += f"Имена: {', '.join(to_names)}\n"
            if to_emails:
                to_info += f"Email: {', '.join(to_emails)}\n"
    
    # Формируем информацию о товарах (для контекста)
    items_info = ""
    if parsed_items:
        items_summary = []
        for item in parsed_items[:10]:  # Ограничиваем до 10 товаров
            art = item.get("art", "") or item.get("sku", "")
            name = item.get("name", "")
            qty = item.get("quantity", 1)
            if art:
                items_summary.append(f"- {art} ({name or 'без названия'}) x{qty}")
        if items_summary:
            items_info = f"\nЗапрашиваемые товары:\n" + "\n".join(items_summary)
    
    # Формируем промпт для LLM
    body_limited = body[:3000] if body else ""  # Увеличиваем лимит для лучшего контекста
    prompt = f"""Ты анализируешь письмо от клиента, который запрашивает товары у менеджера компании.

ВАЖНО: Различай:
- КЛИЕНТ (отправитель письма) - тот, кто запрашивает товары
- МЕНЕДЖЕР (получатель письма) - сотрудник компании, кому пишет клиент

Данные письма:
Тема: {subject}
Отправитель (клиент): {sender}
{to_info}
{items_info}

Текст письма:
{body_limited}

Извлеки и верни JSON со следующими полями:

1. КЛИЕНТ (тот, кто запрашивает):
   - contact_name: полное ФИО клиента (из подписи, текста письма, или имени отправителя)
   - company_name: название компании клиента (если упоминается)
   - contact_email: email клиента (обычно это отправитель {sender}, но проверь в тексте)
   - contact_phone: телефон клиента (мобильный, рабочий - любой найденный)

2. МЕНЕДЖЕР (кому пишет клиент):
   - manager_name: имя/ФИО менеджера (из текста "Уважаемый Иван", "Добрый день, Петр", или из подписи получателя)
   - manager_email: email менеджера (из списка получателей или упоминаний в тексте)

ПРАВИЛА ИЗВЛЕЧЕНИЯ:
- Если в тексте есть обращение "Уважаемый Иван" или "Добрый день, Петр" - это manager_name
- Если есть подпись с именем в конце письма - это может быть contact_name (клиент) или manager_name (если это ответ)
- Телефон ищи в форматах: +7..., 8..., (7...), и т.д.
- Компанию клиента ищи в подписи или в начале письма
- Если информации нет - верни null для соответствующего поля

Верни ТОЛЬКО валидный JSON без дополнительных комментариев."""

    try:
        # Используем LLM для извлечения структурированных данных
        response = await ai_parser.client.chat.completions.create(
            model=ai_parser.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты эксперт по анализу деловой переписки. "
                        "Твоя задача - точно определить, кто клиент (запрашивает товары), "
                        "а кто менеджер (получает запрос). "
                        "Извлекай структурированную информацию: имена, компании, контакты. "
                        "Отвечай ТОЛЬКО валидным JSON без дополнительного текста."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,  # Снижаем температуру для более точного извлечения
        )

        import json
        result = json.loads(response.choices[0].message.content)
        
        # Fallback: если email клиента не найден, используем отправителя
        contact_email = result.get("contact_email") or sender
        
        return {
            "company_name": result.get("company_name"),
            "contact_name": result.get("contact_name"),
            "contact_email": contact_email,
            "contact_phone": result.get("contact_phone"),
            "manager_name": result.get("manager_name"),
            "manager_email": result.get("manager_email"),
        }
    except Exception:
        logger.exception("Ошибка извлечения данных клиента через AI")
        # Fallback: используем отправителя как email клиента
        return {
            "company_name": None,
            "contact_name": None,
            "contact_email": sender,
            "contact_phone": None,
            "manager_name": None,
            "manager_email": None,
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
    parsed_items = []
    for item in items:
        price_raw = getattr(item, "price", 0)
        if price_raw is None:
            price_val = 0.0
        else:
            price_val = float(price_raw)

        parsed_items.append(
            {
                "art": getattr(item, "art", "") or "",
                "name": getattr(item, "name", "") or "",
                "price": price_val,
                "currency": getattr(item, "currency", "KZT") or "KZT",
                "quantity": int(getattr(item, "quantity", 1) or 1),
            }
        )

    # -------- 3. ИЗВЛЕЧЕНИЕ ДАННЫХ КЛИЕНТА И МЕНЕДЖЕРА (AI) --------
    # Получаем список получателей из письма (кому пишет клиент)
    to_recipients = msg_dict.get("toRecipients") or []
    
    client_info = await extract_client_info(
        subject=subject,
        body=body,
        sender=sender,
        to_recipients=to_recipients,
        parsed_items=parsed_items,  # Передаём товары для контекста
    )
    company_name = client_info.get("company_name")
    contact_name = client_info.get("contact_name")
    contact_email = client_info.get("contact_email")
    contact_phone = client_info.get("contact_phone")
    manager_name = client_info.get("manager_name")
    manager_email = client_info.get("manager_email")
    
    # Логируем извлечённую информацию
    logger.info(
        "Извлечена информация из письма requests@...: "
        "клиент=%s, компания=%s, телефон=%s, менеджер=%s, email_менеджера=%s",
        contact_name or "не указан",
        company_name or "не указана",
        contact_phone or "не указан",
        manager_name or "не указан",
        manager_email or "не указан",
    )

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

    # -------- 4.5. УМНЫЙ РОУТИНГ МЕНЕДЖЕРА --------
    assigned_by_id = None

    # Приоритет 1: Ищем менеджера по email или имени, извлеченному AI
    if manager_email or manager_name:
        users = await bitrix_service.search_users(email_query=manager_email, name_query=manager_name)
        if users:
            found_id = users[0].get("ID")
            if found_id:
                assigned_by_id = int(found_id)
                logger.info("Менеджер найден по email/имени: ID=%s", assigned_by_id)

    # Приоритет 2: Ищем в наблюдателях компании
    if not assigned_by_id and company_id:
        company = await bitrix_service.get_company(company_id)
        if company:
            # Пробуем достать наблюдателей
            observers = company.get("OBSERVER_IDS")
            if observers:
                try:
                    if isinstance(observers, list) and observers:
                        assigned_by_id = int(observers[0])
                    elif isinstance(observers, str) and observers.strip():
                        assigned_by_id = int(observers.strip())
                    
                    if assigned_by_id:
                        logger.info("Менеджер взят из наблюдателей компании (OBSERVER_IDS): ID=%s", assigned_by_id)
                except (ValueError, TypeError):
                    pass
            
            # Если в OBSERVER_IDS пусто, фоллбечимся на ответственного за компанию
            if not assigned_by_id:
                comp_assigned = company.get("ASSIGNED_BY_ID")
                if comp_assigned:
                    try:
                        assigned_by_id = int(comp_assigned)
                        logger.info("Менеджер взят из ответственного за компанию (ASSIGNED_BY_ID): ID=%s", assigned_by_id)
                    except (ValueError, TypeError):
                        pass

    # Приоритет 3: Дефолтный ID
    if not assigned_by_id:
        assigned_by_id = DEFAULT_ASSIGNED_BY_ID
        logger.warning(
            "Менеджер не найден (email=%s, name=%s, company_id=%s). Использован дефолтный ID=%s",
            manager_email, manager_name, company_id, assigned_by_id
        )

    # -------- 5. СОЗДАНИЕ СДЕЛКИ В BITRIX24 --------
    deal_id = None
    try:
        deal_id = await deal_service.create_deal_from_email(
            subject=subject,
            sender=sender,
            assigned_by_id=assigned_by_id,
            parsed_items=parsed_items,
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
                bitrix_user_id=assigned_by_id,
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

    # Формируем информацию о клиенте
    client_info_text = ""
    if contact_name:
        client_info_text += f"👤 Клиент: {contact_name}\n"
    if company_name:
        client_info_text += f"🏢 Компания: {company_name}\n"
    if contact_phone:
        client_info_text += f"📞 Телефон: {contact_phone}\n"
    if contact_email and contact_email != sender:
        client_info_text += f"📧 Email: {contact_email}\n"
    
    # Формируем информацию о менеджере
    manager_info_text = ""
    if manager_name:
        manager_info_text += f"👔 Менеджер: {manager_name}\n"
    if manager_email:
        manager_info_text += f"📧 Email менеджера: {manager_email}\n"
    elif not manager_name:
        # Если менеджер не определён, но есть получатели
        if to_recipients:
            manager_emails = []
            for recipient in to_recipients:
                if isinstance(recipient, dict):
                    email = recipient.get("emailAddress", {}).get("address", "")
                    if email:
                        manager_emails.append(email)
                elif isinstance(recipient, str):
                    manager_emails.append(recipient)
            if manager_emails:
                manager_info_text += f"📧 Получатель: {', '.join(manager_emails)}\n"

    deal_text = f"🏢 ID сделки в Битрикс24: #{deal_id}"

    text = (
        "📧 Обработано письмо из requests@...\n"
        f"Тема: {subject}\n"
        f"От: {sender}\n"
    )
    
    if client_info_text:
        text += f"\n{client_info_text}"
    
    if manager_info_text:
        text += f"\n{manager_info_text}"
    
    text += (
        f"\n📦 Товаров спарсено: {len(items_with_status)}\n"
        f"✅ Найдено в прайсах: {found_count}\n"
        f"❌ Не найдено: {not_found_count}\n"
        f"\n{deal_text}"
    )

    # Шлём уведомление всем админам
    for chat_id in get_admin_chat_ids():
        await tg.send_message(chat_id=chat_id, text=text)

    return f"Deal: {deal_id}, Items: {len(items_with_status)}, Found: {found_count}, Not found: {not_found_count}"
