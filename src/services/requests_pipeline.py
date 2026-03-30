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
from src.repositories.analog_repo import AnalogRepository, AnalogRequestRepository
from src.core.bitrix import get_bitrix_client
from src.db.initialize import async_session
from src.app.config import settings
from src.db.models.price_model import PriceModel
from sqlalchemy import select

import logging

logger = logging.getLogger(__name__)

# Bitrix user ID по умолчанию для автоматически созданных сделок
DEFAULT_ASSIGNED_BY_ID = 209


async def extract_client_info(
    subject: str, 
    body: str, 
    sender: str,
    to_recipients: list | None = None,
    parsed_items: list | None = None,
) -> dict:
    """
    Извлекает информацию о клиенте и менеджере из письма с помощью AI и логики доменов.
    
    Логика:
    1. Наши домены: @tpgt-titan.com, @tpgt.kz
    2. МЕНЕДЖЕР: Последний отправитель с нашего домена (кто переслал или прямой получатель).
    3. КЛИЕНТ: Первый (оригинальный) отправитель с внешнего домена в истории пересылки.
    """
    CORPORATE_DOMAINS = ["tpgt-titan.com", "tpgt.kz"]
    
    def is_corporate(email: str) -> bool:
        if not email: return False
        return any(email.lower().endswith(f"@{domain}") for domain in CORPORATE_DOMAINS)

    # 1. Поиск МЕНЕДЖЕРА (последний наш)
    # Если отправитель наш - он и есть менеджер
    manager_email = sender if is_corporate(sender) else None
    
    # 2. Поиск КЛИЕНТА (первый внешний в истории)
    # Если отправитель внешний - он может быть клиентом
    client_email = sender if not is_corporate(sender) else None
    
    # Парсим историю пересылки (Forwarded message)
    # Ищем блоки типа "From: ...", "От: ..."
    import re
    # Регулярка для извлечения email из строк типа "From: Name <email@domain.com>" или просто "email@domain.com"
    email_regex = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    
    # Ищем все упоминания "From:" или "От:" в тексте
    forwarded_from_lines = re.findall(r"(?:From|От|Отправитель):\s*(.*)", body, re.IGNORECASE)
    
    extracted_emails = []
    for line in forwarded_from_lines:
        found = re.findall(email_regex, line)
        if found:
            extracted_emails.extend(found)
    
    # Также проверяем отправителя в самом верху истории
    all_potential_emails = [sender] + extracted_emails
    
    # Определяем клиента: первый внешний email в цепочке (начиная с конца истории, т.е. начала переписки)
    # Но обычно история идет сверху вниз (новое сверху). Оригинальный отправитель в самом низу.
    external_emails = [e for e in all_potential_emails if not is_corporate(e)]
    if external_emails:
        client_email = external_emails[-1] # Самый первый отправитель (дно истории)
        
    # Определяем менеджера: если отправитель корпоративный - он менеджер.
    if not manager_email:
        corp_emails = [e for e in all_potential_emails if is_corporate(e)]
        if corp_emails:
            manager_email = corp_emails[0] # Самый последний переславший (верх истории)

    ai_parser = FuchsAIParser()
    
    # Формируем информацию о получателях для AI
    to_info = ""
    if to_recipients:
        # Извлекаем получателей
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

    # AI теперь помогает только с именами и телефонами, а email-ы мы уже определили надежнее
    body_limited = body[:3000] if body else ""
    prompt = f"""Ты анализируешь историю переписки.
Мы определили:
- КЛИЕНТ (Email): {client_email or 'неизвестно'}
- МЕНЕДЖЕР (Email): {manager_email or 'неизвестно'}

Твоя задача - найти ИМЕНА и ТЕЛЕФОНЫ для этих людей в тексте письма.

Данные письма:
Тема: {subject}
Текст письма:
{body_limited}

Извлеки и верни JSON:
{{
    "contact_name": "ФИО клиента (кто самый первый отправил запрос)",
    "company_name": "компания клиента",
    "contact_phone": "телефон клиента",
    "manager_name": "имя нашего менеджера (кто последний переслал или кому адресовано)"
}}
Верни ТОЛЬКО JSON."""

    try:
        import json
        from google.genai import types

        response = await ai_parser.client.aio.models.generate_content(
            model=ai_parser.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction="Ты эксперт по анализу переписки. Отвечай только JSON.",
                temperature=0.1,
                response_mime_type="application/json",
            ),
        )

        result = json.loads(response.text)

        return {
            "company_name": result.get("company_name"),
            "contact_name": result.get("contact_name"),
            "contact_email": client_email or sender,
            "contact_phone": result.get("contact_phone"),
            "manager_name": result.get("manager_name"),
            "manager_email": manager_email,
        }
    except Exception:
        logger.exception("Ошибка AI уточнения данных")
        return {
            "company_name": None,
            "contact_name": None,
            "contact_email": client_email or sender,
            "contact_phone": None,
            "manager_name": None,
            "manager_email": manager_email,
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
    Enrichment: ищет товары в каталоге (prices) и подбирает аналоги.

    Для каждого товара:
    1. Ищем по артикулу в prices -> "found_in_catalog"
    2. Если не найден, ищем подтверждённые аналоги (product_analogs, status=confirmed):
       - Ровно 1 аналог (UC-02) -> "analog_auto" — подменяем товар, берём цену аналога
       - Несколько аналогов (UC-03) -> "analog_multiple" — требуется выбор менеджера
       - Ничего (UC-04) -> "analog_not_found" — требуется ручной подбор

    Возвращает список dict-ов с полем enrichment_status.
    """
    result_items = []
    analog_repo = AnalogRepository()

    for item in parsed_items:
        art = item.get("art") or item.get("sku", "")
        name = item.get("name", "")
        raw_name = item.get("raw_name")
        quantity = float(item.get("quantity", 1))
        unit = item.get("unit")

        # ---- ШАГ 1: Ищем в каталоге (prices) ----
        price_obj = None
        if art:
            price_obj = await db_session.scalar(
                select(PriceModel).where(PriceModel.art == art)
            )

        if price_obj:
            result_items.append({
                "art": art,
                "sku": art,
                "name": price_obj.name,
                "raw_name": raw_name,
                "price": float(price_obj.price),
                "quantity": quantity,
                "unit": unit or getattr(price_obj, "unit", None),
                "currency": price_obj.currency or "KZT",
                "found": True,
                "enrichment_status": "found_in_catalog",
                "analogs": [],
            })
            continue

        # ---- ШАГ 2: Ищем подтверждённые аналоги ----
        confirmed_analogs = []
        if art:
            confirmed_analogs = await analog_repo.get_confirmed_by_source_code(
                db_session, art.strip().upper()
            )

        if len(confirmed_analogs) == 1:
            # UC-02: Ровно один подтверждённый аналог — автоподмена
            analog = confirmed_analogs[0]
            analog_code = analog.analog_product_code

            # Ищем цену аналога в каталоге
            analog_price_obj = await db_session.scalar(
                select(PriceModel).where(PriceModel.art == analog_code)
            )

            if analog_price_obj:
                result_items.append({
                    "art": analog_code,
                    "sku": analog_code,
                    "name": analog_price_obj.name,
                    "raw_name": raw_name,
                    "original_art": art,
                    "original_name": name,
                    "price": float(analog_price_obj.price),
                    "quantity": quantity,
                    "unit": unit or getattr(analog_price_obj, "unit", None),
                    "currency": analog_price_obj.currency or "KZT",
                    "found": True,
                    "enrichment_status": "analog_auto",
                    "analogs": [{
                        "art": analog.analog_product_code,
                        "name": analog.analog_product_name,
                        "source": analog.supplier_name,
                    }],
                })
            else:
                # Аналог подтверждён, но его нет в прайсе — считаем ненайденным
                result_items.append({
                    "art": art,
                    "sku": art,
                    "name": name or (f"Товар {art}" if art else "Товар без артикула"),
                    "raw_name": raw_name,
                    "price": float(item.get("price", 0)),
                    "quantity": quantity,
                    "unit": unit,
                    "currency": item.get("currency", "KZT"),
                    "found": False,
                    "enrichment_status": "analog_not_in_catalog",
                    "analogs": [{
                        "art": analog.analog_product_code,
                        "name": analog.analog_product_name,
                        "source": analog.supplier_name,
                    }],
                })

        elif len(confirmed_analogs) > 1:
            # UC-03: Несколько подтверждённых аналогов — нужен выбор менеджера
            analogs_list = [
                {
                    "art": a.analog_product_code,
                    "name": a.analog_product_name,
                    "source": a.supplier_name,
                }
                for a in confirmed_analogs
            ]
            result_items.append({
                "art": art,
                "sku": art,
                "name": name or (f"Товар {art}" if art else "Товар без артикула"),
                "raw_name": raw_name,
                "price": float(item.get("price", 0)),
                "quantity": quantity,
                "unit": unit,
                "currency": item.get("currency", "KZT"),
                "found": False,
                "enrichment_status": "analog_multiple",
                "analogs": analogs_list,
            })

        else:
            # UC-04: Аналогов не найдено
            result_items.append({
                "art": art,
                "sku": art,
                "name": name or (f"Товар {art}" if art else "Товар без артикула"),
                "raw_name": raw_name,
                "price": float(item.get("price", 0)),
                "quantity": quantity,
                "unit": unit,
                "currency": item.get("currency", "KZT"),
                "found": False,
                "enrichment_status": "analog_not_found",
                "analogs": [],
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
    extraction_result = {}
    if not items:
        attachment_text = ai_parser.extract_text_from_attachments(attachments)
        extraction_result = await ai_parser.parse_to_objects(body, attachment_text)
        items = extraction_result.get("items", [])

    if not items:
        return "No data"

    # Конвертируем в словари для дальнейшей обработки
    parsed_items = []
    for item in items:
        # Если это объект Pydantic (из Excel) или дикт (из AI)
        art = getattr(item, "art", "") if not isinstance(item, dict) else item.get("art", "")
        name = getattr(item, "name", "") if not isinstance(item, dict) else item.get("name", "")
        raw_name = getattr(item, "raw_name", None) if not isinstance(item, dict) else item.get("raw_name")
        price = getattr(item, "price", 0) if not isinstance(item, dict) else item.get("price", 0)
        currency = getattr(item, "currency", "KZT") if not isinstance(item, dict) else item.get("currency", "KZT")
        quantity = getattr(item, "quantity", 1.0) if not isinstance(item, dict) else item.get("quantity", 1.0)
        unit = getattr(item, "unit", None) if not isinstance(item, dict) else item.get("unit")

        parsed_items.append(
            {
                "art": art or "",
                "name": name or "",
                "raw_name": raw_name,
                "price": float(price or 0),
                "currency": currency or "KZT",
                "quantity": float(quantity or 1.0),
                "unit": unit,
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

    # -------- 5. ENRICHMENT: ПОИСК ТОВАРОВ В ПРАЙСАХ И АНАЛОГАХ --------
    async with async_session() as db_session:
        items_with_status = await find_items_in_prices(db_session, parsed_items)

        # Классифицируем результаты enrichment
        found_count = sum(1 for i in items_with_status if i.get("found"))
        auto_analog_count = sum(
            1 for i in items_with_status if i.get("enrichment_status") == "analog_auto"
        )
        # Товары, которые блокируют автоматическое создание сделки
        blocking_items = [
            i for i in items_with_status
            if i.get("enrichment_status") in ("analog_multiple", "analog_not_found", "analog_not_in_catalog")
        ]
        has_blocking = len(blocking_items) > 0

        # -------- 5.1. ЕСЛИ ЕСТЬ БЛОКИРУЮЩИЕ ПОЗИЦИИ — НЕ СОЗДАЁМ СДЕЛКУ --------
        if has_blocking:
            # Сохраняем analog_requests для каждой блокирующей позиции
            analog_request_repo = AnalogRequestRepository()
            for bl_item in blocking_items:
                await analog_request_repo.create(
                    db_session,
                    product_code=bl_item.get("art"),
                    product_name=bl_item.get("name"),
                    brand=None,
                    supplier=None,
                    deal_id=None,  # сделка не создана
                    client_id=str(contact_email) if contact_email else None,
                    manager_id=None,
                    request_status="pending",
                )
            await db_session.commit()

            logger.warning(
                "Заявка из письма '%s' приостановлена: %d позиций требуют действий менеджера",
                subject, len(blocking_items),
            )

            # Уведомление о приостановленной заявке
            await _send_blocked_notification(
                tg=tg,
                subject=subject,
                sender=sender,
                contact_name=contact_name,
                company_name=company_name,
                contact_phone=contact_phone,
                contact_email=contact_email,
                manager_name=manager_name,
                manager_email=manager_email,
                to_recipients=to_recipients,
                items_with_status=items_with_status,
                blocking_items=blocking_items,
                found_count=found_count,
                auto_analog_count=auto_analog_count,
            )

            return (
                f"Blocked: {len(blocking_items)} items need manager action. "
                f"Total: {len(items_with_status)}, Found: {found_count}, "
                f"Auto-analog: {auto_analog_count}"
            )

    # -------- 6. СОЗДАНИЕ СДЕЛКИ В BITRIX24 (только если всё найдено) --------
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
        return "Error creating deal"

    if not deal_id:
        return "Failed to create deal"

    # -------- 7. СОЗДАНИЕ КОРЗИНЫ (OFFER) --------
    async with async_session() as db_session:
        offer_service = OfferService(db_session)
        currency = items_with_status[0].get("currency", "KZT") if items_with_status else "KZT"

        try:
            offer = await offer_service.create_offer_for_deal(
                deal_id=deal_id,
                bitrix_user_id=assigned_by_id,
                items=items_with_status,
                currency=currency,
                payment_terms=extraction_result.get("payment_terms"),
                delivery_terms=extraction_result.get("delivery_terms"),
                warranty_terms=extraction_result.get("warranty_terms"),
                manager_email=manager_email,
                client_email=contact_email,
                incoterms=extraction_result.get("incoterms"),
                deadline=extraction_result.get("deadline"),
                delivery_place=extraction_result.get("delivery_place"),
                notes=", ".join(extraction_result.get("dates", [])) if extraction_result.get("dates") else extraction_result.get("notes"),
                client_company_name=company_name,
                client_address=extraction_result.get("delivery_place"),
                subject=extraction_result.get("subject"),
            )
            logger.info(
                "Создана корзина offer_id=%s для сделки deal_id=%s, товаров: %d",
                offer.id,
                deal_id,
                len(items_with_status),
            )
        except Exception:
            logger.exception("Ошибка создания корзины для сделки deal_id=%s", deal_id)

    # -------- 8. TELEGRAM NOTIFICATION (успешная сделка) --------
    not_found_count = len(items_with_status) - found_count

    text = _build_success_notification(
        subject=subject,
        sender=sender,
        contact_name=contact_name,
        company_name=company_name,
        contact_phone=contact_phone,
        contact_email=contact_email,
        manager_name=manager_name,
        manager_email=manager_email,
        to_recipients=to_recipients,
        items_with_status=items_with_status,
        found_count=found_count,
        auto_analog_count=auto_analog_count,
        not_found_count=not_found_count,
        deal_id=deal_id,
    )

    for chat_id in get_admin_chat_ids():
        await tg.send_message(chat_id=chat_id, text=text)

    return f"Deal: {deal_id}, Items: {len(items_with_status)}, Found: {found_count}, Auto-analog: {auto_analog_count}"


# ---------------------------------------------------------------------------
# Вспомогательные функции для уведомлений
# ---------------------------------------------------------------------------

def _build_success_notification(
    *,
    subject, sender, contact_name, company_name, contact_phone, contact_email,
    manager_name, manager_email, to_recipients, items_with_status,
    found_count, auto_analog_count, not_found_count, deal_id,
) -> str:
    """Формирует текст уведомления об успешно созданной сделке."""
    text = (
        "📧 Обработано письмо из requests@...\n"
        f"Тема: {subject}\n"
        f"От: {sender}\n"
    )

    text += _format_client_manager_info(
        contact_name, company_name, contact_phone, contact_email, sender,
        manager_name, manager_email, to_recipients,
    )

    text += (
        f"\n📦 Товаров спарсено: {len(items_with_status)}\n"
        f"✅ Найдено в каталоге: {found_count}\n"
    )
    if auto_analog_count:
        text += f"🔄 Автоподмена по аналогу: {auto_analog_count}\n"

    # Детали автозаменённых товаров
    auto_items = [i for i in items_with_status if i.get("enrichment_status") == "analog_auto"]
    if auto_items:
        text += "\n🔄 АВТОМАТИЧЕСКИ ПОДМЕНЁННЫЕ ПОЗИЦИИ:\n"
        for item in auto_items:
            text += (
                f"• {item.get('original_name', '?')} (арт. {item.get('original_art', '?')}) "
                f"→ {item['name']} (арт. {item['art']})\n"
            )

    text += f"\n🏢 ID сделки в Битрикс24: #{deal_id}"
    return text


async def _send_blocked_notification(
    *,
    tg, subject, sender, contact_name, company_name, contact_phone, contact_email,
    manager_name, manager_email, to_recipients, items_with_status,
    blocking_items, found_count, auto_analog_count,
):
    """Отправляет уведомление о заблокированной заявке (ожидает действий менеджера)."""
    text = (
        "🚫 ЗАЯВКА ПРИОСТАНОВЛЕНА — требуются действия менеджера\n"
        f"Тема: {subject}\n"
        f"От: {sender}\n"
    )

    text += _format_client_manager_info(
        contact_name, company_name, contact_phone, contact_email, sender,
        manager_name, manager_email, to_recipients,
    )

    text += (
        f"\n📦 Товаров спарсено: {len(items_with_status)}\n"
        f"✅ Найдено в каталоге: {found_count}\n"
    )
    if auto_analog_count:
        text += f"🔄 Автоподмена по аналогу: {auto_analog_count}\n"
    text += f"⛔ Требуют действий: {len(blocking_items)}\n"

    text += "\n⚠️ ПОЗИЦИИ, ТРЕБУЮЩИЕ ДЕЙСТВИЙ:\n"
    for item in blocking_items:
        status = item.get("enrichment_status")
        item_name = item.get("name") or item.get("art") or "???"
        text += f"• {item_name}"
        if item.get("art"):
            text += f" (арт. {item.get('art')})"

        if status == "analog_multiple":
            text += " — найдено несколько аналогов, выберите в Mini App\n"
            for a in item.get("analogs", []):
                text += f"   - {a.get('name', '?')} ({a.get('art', '?')})\n"
        elif status == "analog_not_found":
            text += " — аналог не найден\n"
        elif status == "analog_not_in_catalog":
            text += " — аналог найден, но отсутствует в прайсе\n"
        else:
            text += "\n"

    text += "\n💡 Откройте Mini App для обработки заявки."

    for chat_id in get_admin_chat_ids():
        await tg.send_message(chat_id=chat_id, text=text)


def _format_client_manager_info(
    contact_name, company_name, contact_phone, contact_email, sender,
    manager_name, manager_email, to_recipients,
) -> str:
    """Общий блок информации о клиенте и менеджере для уведомлений."""
    text = ""

    if contact_name:
        text += f"\n👤 Клиент: {contact_name}\n"
    if company_name:
        text += f"🏢 Компания: {company_name}\n"
    if contact_phone:
        text += f"📞 Телефон: {contact_phone}\n"
    if contact_email and contact_email != sender:
        text += f"📧 Email: {contact_email}\n"

    if manager_name:
        text += f"\n👔 Менеджер: {manager_name}\n"
    if manager_email:
        text += f"📧 Email менеджера: {manager_email}\n"
    elif not manager_name and to_recipients:
        manager_emails = []
        for recipient in to_recipients:
            if isinstance(recipient, dict):
                email = recipient.get("emailAddress", {}).get("address", "")
                if email:
                    manager_emails.append(email)
            elif isinstance(recipient, str):
                manager_emails.append(recipient)
        if manager_emails:
            text += f"\n📧 Получатель: {', '.join(manager_emails)}\n"

    return text
