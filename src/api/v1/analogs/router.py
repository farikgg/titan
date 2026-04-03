from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from src.db.initialize import get_db
from src.core.auth import get_tg_user_or_admin
from src.repositories.analog_repo import AnalogRepository, AnalogRequestRepository
from src.db.models.user_model import UserModel
from src.db.models.product_analog_model import ProductAnalogModel
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

router = APIRouter(prefix="/analogs", tags=["Analogs"])

class AnalogSearchResponse(BaseModel):
    id: int
    source_product_code: str
    source_product_name: str | None = None
    analog_product_code: str
    analog_product_name: str | None = None
    supplier_name: str | None = None
    status: str
    confidence_level: float | None = None
    
    model_config = ConfigDict(from_attributes=True)

@router.get("/search", response_model=List[AnalogSearchResponse])
async def search_analogs(
    code: str | None = Query(None),
    name: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: UserModel = Depends(get_tg_user_or_admin),
):
    """Ищет агрегированные подтверждённые аналоги для заданного артикула или названия"""
    if not code and not name:
        return []
        
    repo = AnalogRepository()
    analogs = await repo.get_all_for_product(db, code=code, name=name)
    return analogs

class AnalogRequestResponse(BaseModel):
    id: int
    product_name: str | None = None
    product_code: str | None = None
    brand: str | None = None
    supplier: str | None = None
    request_status: str
    
    model_config = ConfigDict(from_attributes=True)

@router.get("/pending", response_model=List[AnalogRequestResponse])
async def get_pending_requests(
    db: AsyncSession = Depends(get_db),
    user: UserModel = Depends(get_tg_user_or_admin),
):
    """Возвращает список заявок на аналог ожидающих ответа (статус pending)"""
    repo = AnalogRequestRepository()
    requests = await repo.get_pending(db)
    return requests

@router.patch("/{analog_id}/confirm")
async def confirm_analog(
    analog_id: int,
    db: AsyncSession = Depends(get_db),
    user: UserModel = Depends(get_tg_user_or_admin),
):
    """Подтверждает новый (new) спарсенный аналог, делая его confirmed"""
    analog = await db.scalar(select(ProductAnalogModel).where(ProductAnalogModel.id == analog_id))
    if not analog:
        raise HTTPException(status_code=404, detail="Analog not found")
        
    analog.status = "confirmed"
    analog.confirmed_by = user.id
    
    await db.commit()
    return {"status": "success", "analog_id": analog.id}
