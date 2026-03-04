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


@router.post("/{offer_id}/generate-pdf")
async def generate_pdf(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_tg_user),
):
    """
    Запускает генерацию PDF для коммерческого предложения.
    Генерация выполняется асинхронно в Celery.
    
    Возвращает task_id для отслеживания статуса.
    """
    service = OfferService(db)
    
    try:
        offer = await service.get_offer_with_items(offer_id)
    except AttributeError:
        # get_offer_with_items может упасть, если offer не найден
        raise HTTPException(status_code=404, detail="Offer not found")
    
    if not offer or not offer.get("id"):
        raise HTTPException(status_code=404, detail="Offer not found")
    
    if not offer.get("items"):
        raise HTTPException(status_code=400, detail="Offer is empty. Add items before generating PDF.")
    
    # Запускаем задачу генерации PDF
    # Примечание: chat_id не используется в REST API, но нужен для Telegram уведомлений
    # Используем 0 как заглушку, так как в REST API нет chat_id
    task = generate_offer_pdf_task.delay(offer_id, 0)
    
    return {
        "task_id": task.id,
        "status": "queued",
        "message": "PDF generation started"
    }
