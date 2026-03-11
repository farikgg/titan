from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated

from src.db.initialize import get_db
from src.services.offer_service import OfferService
from src.core.auth import get_tg_user
from src.worker.tasks import generate_offer_pdf_task
from src.app.config import settings

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


@router.post("/draft")
async def create_draft(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_user_or_admin_token),
):
    """
    Создаёт (или возвращает существующий) черновик КП.

    Авторизация:
      - через X-Telegram-Init-Data (TMA), или
      - через admin token в заголовке `token`.

    В варианте с admin token черновик создаётся на «системного» пользователя.
    """
    service = OfferService(db)
    # Для admin token у нас нет Telegram-пользователя, поэтому создаём
    # черновик на условного системного user_id=1.
    # В TMA по-прежнему используется get_or_create_draft по реальному user.id.
    offer = await service.get_or_create_draft(user_id=1)
    await db.commit()
    return {"offer_id": offer.id}


@router.post("/{offer_id}/add/{sku}")
async def add_item(
    offer_id: int,
    sku: str,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_user_or_admin_token),
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
    user=Depends(get_tg_user),
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


@router.get("/{offer_id}")
async def get_offer(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_user_or_admin_token),
):
    service = OfferService(db)
    return await service.get_offer_with_items(offer_id)


@router.post("/{offer_id}/clear")
async def clear_offer(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_user_or_admin_token),
):
    service = OfferService(db)
    await service.clear_offer(offer_id)
    await db.commit()
    return {"status": "cleared"}


from pydantic import BaseModel


class OfferConvertRequest(BaseModel):
    company_id: int | None = None
    contact_id: int | None = None


class UpdateOfferTermsRequest(BaseModel):
    payment_terms: str | None = None
    delivery_terms: str | None = None
    warranty_terms: str | None = None

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


@router.post("/{offer_id}/convert")
async def convert(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_tg_user),
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

    deal_id = await service.convert_to_bitrix(
        offer_id=offer_id,
        assigned_by_id=user.bitrix_user_id,
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
            supplier_type=body.supplier_type,
            fuchs_margin_pct=body.fuchs_margin_pct,
            fuchs_vat_enabled=body.fuchs_vat_enabled,
            fuchs_vat_pct=body.fuchs_vat_pct,
            skf_delivery_pct=body.skf_delivery_pct,
            skf_duty_pct=body.skf_duty_pct,
            skf_margin_pct=body.skf_margin_pct,
            skf_vat_enabled=body.skf_vat_enabled,
            skf_vat_pct=body.skf_vat_pct,
        )
        return {"status": "updated"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{offer_id}/generate-pdf")
async def generate_pdf(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_tg_user),
):
    """
    Запускает генерацию PDF (та же логика, что в боте).

    ВАЖНО: PDF и статус отправляются пользователю через Telegram-бота
    в личные сообщения (chat_id = user.tg_id).
    """
    chat_id = user.tg_id  # в приватном чате chat_id == tg_id
    task = generate_offer_pdf_task.delay(offer_id, chat_id)
    return {"task_id": task.id, "status": "queued"}
