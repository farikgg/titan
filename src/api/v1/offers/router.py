from fastapi import APIRouter, Depends, HTTPException, Request, Header, Body
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated

from src.db.initialize import get_db
from src.db.models.user_model import UserModel
from src.repositories.user_repo import UserRepository
from src.services.offer_service import OfferService
from src.core.auth import get_tg_user, get_tg_user_or_admin
from src.worker.tasks import generate_offer_pdf_task
from src.app.config import settings
from src.core.bitrix import get_bitrix_client
from src.services.bitrix_service import BitrixService
from src.services.deal_service import DealService
from src.services.price_service import PriceService
from src.core.enums import Role

router = APIRouter(prefix="/offers", tags=["Offers"])


async def verify_user_or_admin_token(
    request: Request,
    token: Annotated[str | None, Header()] = None,
):
    """
    Пропускаем либо пользователя из Telegram (X-Telegram-Init-Data),
    либо запрос с корректным ADMIN_SECRET_TOKEN в header `token`.
    """
    # Если пришёл initData от Telegram Mini App — считаем, что фронт авторизован.
    x_telegram_init_data = request.headers.get("X-Telegram-Init-Data")
    if x_telegram_init_data:
        return True

    # Иначе проверяем admin token
    if token and token == settings.ADMIN_SECRET_TOKEN:
        return True

    raise HTTPException(status_code=401, detail="Unauthorized: need Telegram init data or valid admin token")


class DraftRequest(BaseModel):
    deal_id: int | None = None


@router.post("/draft")
async def create_draft(
    body: DraftRequest = Body(default_factory=DraftRequest),
    db: AsyncSession = Depends(get_db),
    user: UserModel = Depends(get_tg_user_or_admin),
):
    service = OfferService(db)

    if body.deal_id:
        from src.services.bitrix_service import BitrixService
        from src.core.bitrix import get_bitrix_client

        bx = get_bitrix_client()
        bitrix = BitrixService(bx)

        deal = await bitrix.get_deal(body.deal_id)
        if not deal:
            raise HTTPException(status_code=404, detail="Сделка не найдена в Bitrix")

        company_id = deal.get("COMPANY_ID")
        company = await bitrix.get_company(int(company_id)) if company_id else {}

        products = await bitrix.get_deal_products(body.deal_id)

        items = [
            {
                "sku": p.get("PRODUCT_ID") or "",
                "name": p.get("PRODUCT_NAME", "Без названия"),
                "price": float(p.get("PRICE", 0)),
                "quantity": float(p.get("QUANTITY", 1)),
                "unit": p.get("MEASURE_NAME", "шт"),
                "found": True,
            }
            for p in products
        ]

        offer = await service.create_offer_for_deal(
            deal_id=body.deal_id,
            bitrix_user_id=int(deal.get("ASSIGNED_BY_ID", 1)),
            items=items,
            currency=deal.get("CURRENCY_ID", "KZT"),
            client_company_name=company.get("TITLE") if company else None,
            subject=deal.get("TITLE"),
        )
    else:
        offer = await service.get_or_create_draft(user.id)

    await db.commit()
    return {"offer_id": offer.id}


@router.post("/{offer_id}/add/{sku}")
async def add_item(
    offer_id: int,
    sku: str,
    db: AsyncSession = Depends(get_db),
    user: UserModel = Depends(get_tg_user_or_admin),
):
    service = OfferService(db)
    await service.add_item(offer_id, sku)
    await db.commit()
    return {"status": "added"}


@router.delete("/{offer_id}/remove/{sku}")
async def remove_item(
    offer_id: int,
    sku: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_tg_user_or_admin),
):
    service = OfferService(db)
    try:
        await service.remove_item(offer_id, sku)
        return {"status": "removed"}
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=error_msg)
        raise HTTPException(status_code=400, detail=error_msg)


class UpdateOfferItemRequest(BaseModel):
    quantity: float
    price: float
    unit: str | None = None


@router.put("/{offer_id}/items/{sku}")
async def update_item(
    offer_id: int,
    sku: str,
    body: UpdateOfferItemRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_tg_user_or_admin),
):
    """Обновляет количество, цену и единицу измерения (шт/кг) для товара в корзине."""
    service = OfferService(db)
    try:
        await service.update_item(
            offer_id=offer_id,
            sku=sku,
            quantity=body.quantity,
            price=body.price,
            unit=body.unit,
        )
        return {"status": "updated"}
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=error_msg)
        raise HTTPException(status_code=400, detail=error_msg)


@router.get("/{offer_id}")
async def get_offer(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_user_or_admin_token),
):
    service = OfferService(db)
    return await service.get_offer_with_items(offer_id)


@router.get("/history/me")
async def get_my_offer_history(
    db: AsyncSession = Depends(get_db),
    user: UserModel = Depends(get_tg_user_or_admin),
    tg_id: int | None = None,
):
    """
    История сделок для профиля.
    Ранее возвращала список КП (OfferModel), теперь возвращает список сделок
    из Bitrix24 для данного пользователя.
    """
    if tg_id is not None and user.tg_id is None:
        repo = UserRepository(db)
        target_user = await repo.get_by_tg_id(tg_id)
        if not target_user:
            raise HTTPException(status_code=404, detail=f"User with tg_id={tg_id} not found")
    else:
        target_user = user

    bx = get_bitrix_client()
    bitrix_service = BitrixService(bx)
    
    # Чтобы в профиле показывались СТРОГО только свои сделки (даже для админов)
    # мы напрямую дергаем get_deals по bitrix_user_id текущего юзера.
    bitrix_user_id = getattr(target_user, "bitrix_user_id", None)
    if bitrix_user_id:
        deals = await bitrix_service.get_deals(bitrix_user_id=bitrix_user_id)
    else:
        deals = []
    
    stage_name_map = {
        "C9:NEW": "Интерес или ТКП",
        "C9:FINAL_INVOICE": "Договор заключен. В работе",
        "C9:EXECUTING": "АВР и Накладная подписаны",
        "C9:WON": "Сделка успешна",
        "C9:LOSE": "Нет финансирования",
        "C9:APOLOGY": "Анализ причины провала",
        "C9:UC_BVSRBV": "Конкуренты",
    }

    result = []
    for d in deals:
        raw_title = d.get("TITLE") or ""
        # В Битриксе сделки создавались с префиксом "КП #...", фронт хочет видеть "Сделка #..."
        if raw_title.startswith("КП #"):
            title = raw_title.replace("КП #", "Сделка #", 1)
        elif not raw_title:
            title = f"Сделка #{d.get('ID')}"
        else:
            title = raw_title

        result.append({
            "id": int(d.get("ID", 0)),
            "title": title,
            "status": stage_name_map.get(d.get("STAGE_ID"), d.get("STAGE_ID", "NEW")),
            "total": float(d.get("OPPORTUNITY", 0)),
            "currency": d.get("CURRENCY_ID", "KZT"),
            "assigned_by_id": d.get("ASSIGNED_BY_ID"),
        })

    return result


@router.get("/by-deal/{deal_id}")
async def get_offer_by_deal(
    deal_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_user_or_admin_token),
):
    """
    Возвращает оффер (КП) и его товары по ID сделки Bitrix24.
    Удобно вызывать из карточки сделки (воронка 9 / канбан),
    где в интерфейсе нет отдельного списка товаров.
    """
    service = OfferService(db)
    data = await service.get_offer_by_bitrix_deal(deal_id)
    if not data:
        raise HTTPException(status_code=404, detail="Offer for this deal not found")
    return data


@router.post("/{offer_id}/clear")
async def clear_offer(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
    user: UserModel = Depends(get_tg_user_or_admin),
):
    service = OfferService(db)
    await service.clear_offer(offer_id)
    await db.commit()
    return {"status": "cleared"}


from pydantic import BaseModel


class OfferConvertRequest(BaseModel):
    company_id: int | None = None
    contact_id: int | None = None
    assigned_by_id: int | None = None  # Bitrix user id (ответственный)
    currency: str | None = None  # Валюта КП


class UpdateOfferTermsRequest(BaseModel):
    payment_terms: str | None = None
    delivery_terms: str | None = None
    warranty_terms: str | None = None
    lead_time: str | None = None

    # Валюта КП (KZT / RUB / EUR / USD и т.п.)
    currency: str | None = None

    # -----------------------------
    # Параметры расчёта цен
    # -----------------------------
    # Тип поставщика для текущего КП:
    #   - "fuchs" → формулы для масел/смазок
    #   - "skf"   → формулы для оборудования SKF
    supplier_type: str | None = None  # "fuchs" | "skf"

    # FUCHS
    fuchs_margin_pct: float | None = None
    fuchs_vat_enabled: bool | None = None
    fuchs_vat_pct: float | None = None

    # SKF
    skf_delivery_pct: float | None = None
    skf_duty_pct: float | None = None
    skf_margin_pct: float | None = None
    skf_vat_enabled: bool | None = None
    skf_vat_pct: float | None = None

    # Поля для шапки PDF
    client_company_name: str | None = None
    client_address: str | None = None
    subject: str | None = None


@router.post("/{offer_id}/convert")
async def convert(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_tg_user_or_admin),
    body: OfferConvertRequest | None = None,
):
    service = OfferService(db)
    # Делаем логику такой же, как при авто‑создании из письма FUCHS:
    # если не указать явно, внутри будет использован DEFAULT_ASSIGNED_BY_ID.
    # Здесь можем назначать ответственным текущего пользователя Bitrix.
    kwargs: dict = {}
    if body:
        if body.company_id is not None:
            kwargs["company_id"] = body.company_id
        if body.contact_id is not None:
            kwargs["contact_id"] = body.contact_id

    # Валюта: чтобы сделка получила выбранную валюту
    if body and body.currency:
        await service.update_terms(offer_id, currency=body.currency)

    # Ответственный: менеджер может выбрать только себя, руководитель/админ — любого
    assigned_by_id = user.bitrix_user_id
    if body and body.assigned_by_id is not None:
        if user.role == Role.manager.value and body.assigned_by_id != user.bitrix_user_id:
            raise HTTPException(status_code=403, detail="Managers can assign only themselves")
        assigned_by_id = body.assigned_by_id

    deal_id = await service.convert_to_bitrix(
        offer_id=offer_id,
        assigned_by_id=assigned_by_id,
        **kwargs,
    )
    await db.commit()
    return {"bitrix_deal_id": deal_id}


@router.post("/{offer_id}/terms")
async def update_terms(
    offer_id: int,
    body: UpdateOfferTermsRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_user_or_admin_token),
):
    """
    Обновляет текстовые поля условий КП:
      - payment_terms
      - delivery_terms
      - warranty_terms
    Любое поле можно не передавать — оно не изменится.
    """
    service = OfferService(db)
    try:
        await service.update_terms(
            offer_id,
            payment_terms=body.payment_terms,
            delivery_terms=body.delivery_terms,
            warranty_terms=body.warranty_terms,
            lead_time=body.lead_time,
            currency=body.currency,
            supplier_type=body.supplier_type,
            fuchs_margin_pct=body.fuchs_margin_pct,
            fuchs_vat_enabled=body.fuchs_vat_enabled,
            fuchs_vat_pct=body.fuchs_vat_pct,
            skf_delivery_pct=body.skf_delivery_pct,
            skf_duty_pct=body.skf_duty_pct,
            skf_margin_pct=body.skf_margin_pct,
            skf_vat_enabled=body.skf_vat_enabled,
            skf_vat_pct=body.skf_vat_pct,
            client_company_name=body.client_company_name,
            client_address=body.client_address,
            subject=body.subject,
        )
        return {"status": "updated"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{offer_id}/generate-pdf")
async def generate_pdf(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_tg_user_or_admin),
):
    """
    Запускает генерацию PDF (та же логика, что в боте).

    ВАЖНО: PDF и статус отправляются пользователю через Telegram-бота
    в личные сообщения (chat_id = user.tg_id).
    """
    chat_id = user.tg_id  # в приватном чате chat_id == tg_id
    task = generate_offer_pdf_task.delay(offer_id, chat_id)
    return {"task_id": task.id, "status": "queued"}


@router.post("/sync-from-deal/{deal_id}")
async def sync_offer_from_deal(
    deal_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_user_or_admin_token),
):
    """
    Создаёт (или переиспользует) offer для существующей сделки Bitrix по её ID,
    подтягивая товары из `crm.deal.productrows.get`.

    Нужен для того, чтобы:
    - по уже созданной в Bitrix сделке подтянуть товары в Titan,
    - показать их в TMA,
    - уметь сгенерировать КП (PDF) по этим товарам.
    """
    # 1. Получаем сделку и её товары из Bitrix
    bx = get_bitrix_client()
    bitrix = BitrixService(bx)

    deal = await bitrix.get_deal(deal_id)
    if not deal:
        raise HTTPException(status_code=404, detail=f"Bitrix deal {deal_id} not found")

    products = await bitrix.get_deal_products(deal_id)

    # Если в сделке нет товаров — нет смысла создавать offer
    if not products:
        raise HTTPException(
            status_code=400,
            detail=f"Bitrix deal {deal_id} has no products",
        )

    # 2. Готовим список товаров в формате, который понимает OfferService.create_offer_for_deal
    currency = deal.get("CURRENCY_ID") or "KZT"
    items: list[dict] = []
    for p in products:
        name = p.get("PRODUCT_NAME") or "Товар"
        price = float(p.get("PRICE", 0) or 0)
        qty_raw = p.get("QUANTITY", 1) or 1
        try:
            quantity = int(qty_raw)
        except (TypeError, ValueError):
            quantity = 1

        items.append(
            {
                "sku": name,  # в Bitrix нет явного артикула, используем название
                "name": name,
                "price": price,
                "quantity": quantity,
                "currency": currency,
                "found": False,  # эти товары пришли не из прайса
            }
        )

    # 3. Определяем Bitrix user ID ответственного
    assigned_by_id_raw = deal.get("ASSIGNED_BY_ID")
    try:
        assigned_by_id = int(assigned_by_id_raw) if assigned_by_id_raw else 109
    except (TypeError, ValueError):
        assigned_by_id = 109

    # 4. Создаём или переиспользуем offer для этой сделки
    service = OfferService(db)
    offer = await service.create_offer_for_deal(
        deal_id=deal_id,
        bitrix_user_id=assigned_by_id,
        items=items,
        currency=currency,
    )

    # 5. Возвращаем offer с товарами в удобном формате
    return await service.get_offer_with_items(offer.id)
