from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.initialize import get_db
from src.services.offer_service import OfferService
from src.core.auth import get_tg_user
from src.worker.tasks import generate_offer_pdf_task

router = APIRouter(prefix="/offers", tags=["Offers"])


@router.post("/draft")
async def create_draft(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_tg_user),
):
    service = OfferService(db)
    # Используем get_or_create_draft, чтобы работало даже в старых версиях сервиса
    offer = await service.get_or_create_draft(user.id)
    await db.commit()
    return {"offer_id": offer.id}


@router.post("/{offer_id}/add/{sku}")
async def add_item(
    offer_id: int,
    sku: str,
    db: AsyncSession = Depends(get_db),
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
):
    service = OfferService(db)
    return await service.get_offer_with_items(offer_id)


@router.post("/{offer_id}/clear")
async def clear_offer(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
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
    user=Depends(get_tg_user),
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
