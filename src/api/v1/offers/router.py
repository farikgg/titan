from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.initialize import get_db
from src.services.offer_service import OfferService
from src.core.auth import get_tg_user

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
):
    service = OfferService(db)
    await service.remove_item(offer_id, sku)
    await db.commit()
    return {"status": "removed"}


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


@router.post("/{offer_id}/convert")
async def convert(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = OfferService(db)
    deal_id = await service.convert_to_bitrix(offer_id)
    await db.commit()
    return {"bitrix_deal_id": deal_id}
