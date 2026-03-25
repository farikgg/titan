import logging
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.initialize import get_db
from src.schemas.price_schema import PriceCreate, PriceRead
from src.services.price_service import PriceService
from src.core.rbac import require_permission
from src.repositories.analog_repo import AnalogRepository
from src.services.fuchs_price_report_service import FuchsPriceReportService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/prices", tags=["Prices"])
price_service = PriceService()
analog_repo = AnalogRepository()


# ──────────────────────────────────────────────
#  Базовые CRUD (существующие)
# ──────────────────────────────────────────────

@router.post(
    "/",
    response_model=PriceRead,
    dependencies=[Depends(require_permission("prices.write"))],
)
async def create_price(
    price_in: PriceCreate,
    db: AsyncSession = Depends(get_db),
):
    return await price_service.add_new_price(db, price_in)


@router.get(
    "/",
    response_model=list[PriceRead],
    dependencies=[Depends(require_permission("prices.read"))],
)
async def get_all_prices(
    db: AsyncSession = Depends(get_db),
):
    return await price_service.get_prices_list(db)


@router.get(
    "/search/{art}",
    response_model=PriceRead,
    dependencies=[Depends(require_permission("prices.read"))],
)
async def search_single(
    art: str,
    db: AsyncSession = Depends(get_db),
):
    return await price_service.get_price(db, art)


# ──────────────────────────────────────────────
#  Excel Export
# ──────────────────────────────────────────────

@router.get(
    "/export",
    dependencies=[Depends(require_permission("prices.read"))],
    summary="Скачать Excel отчёт по ценам FUCHS (статусы + unit price)",
)
async def export_prices_excel(
    db: AsyncSession = Depends(get_db),
):
    """
    Генерирует и возвращает Excel файл с ценами FUCHS.
    Листы: expired / expiring_soon / all / analogs
    """
    report_service = FuchsPriceReportService(expiring_days_threshold=7)

    output_dir = Path("/tmp/titan_reports")
    out_path = await report_service.build_report_xlsx(db, output_dir=output_dir)

    return FileResponse(
        path=str(out_path),
        filename=out_path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ──────────────────────────────────────────────
#  Аналоги товаров
# ──────────────────────────────────────────────

class AnalogResponse(BaseModel):
    id: int
    source_art: str
    analog_art: str
    analog_name: str | None = None
    analog_source: str | None = None
    notes: str | None = None
    created_at: datetime | None = None

    class Config:
        from_attributes = True


class AddAnalogRequest(BaseModel):
    analog_art: str
    analog_name: str | None = None
    analog_source: str | None = None
    notes: str | None = None


@router.get(
    "/{art}/analogs",
    response_model=list[AnalogResponse],
    dependencies=[Depends(require_permission("prices.read"))],
    summary="Получить аналоги товара",
)
async def get_analogs(
    art: str,
    db: AsyncSession = Depends(get_db),
):
    return await analog_repo.get_by_source_art(db, art.strip().upper())


@router.post(
    "/{art}/analogs",
    response_model=AnalogResponse,
    dependencies=[Depends(require_permission("prices.write"))],
    summary="Добавить аналог товара",
)
async def add_analog(
    art: str,
    body: AddAnalogRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        analog = await analog_repo.create(
            db,
            source_art=art.strip().upper(),
            analog_art=body.analog_art.strip().upper(),
            analog_name=body.analog_name,
            analog_source=body.analog_source,
            notes=body.notes,
        )
        await db.commit()
        return analog
    except Exception as e:
        await db.rollback()
        if "uq_analog_pair" in str(e):
            raise HTTPException(
                status_code=409,
                detail=f"Аналог {body.analog_art} уже существует для товара {art}",
            )
        raise


@router.delete(
    "/analogs/{analog_id}",
    dependencies=[Depends(require_permission("prices.write"))],
    summary="Удалить аналог",
)
async def delete_analog(
    analog_id: int,
    db: AsyncSession = Depends(get_db),
):
    deleted = await analog_repo.delete_by_id(db, analog_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Аналог не найден")
    await db.commit()
    return {"deleted": True, "id": analog_id}


# ──────────────────────────────────────────────
#  Ретро-пересчёт unit_price
# ──────────────────────────────────────────────

@router.post(
    "/recalculate-unit-prices",
    dependencies=[Depends(require_permission("prices.write"))],
    summary="Пересчитать unit_price для всех записей в БД",
)
async def recalculate_unit_prices(
    db: AsyncSession = Depends(get_db),
):
    """
    Ретро-расчёт: для всех PriceModel, где есть container_size,
    пересчитывает unit_price и unit_measure.
    """
    from src.db.models.price_model import PriceModel
    from sqlalchemy import select

    result = await db.execute(select(PriceModel))
    prices = list(result.scalars().all())

    updated = 0
    flagged = 0
    for p in prices:
        if p.container_size and p.price:
            unit_price, unit_measure = PriceService.calculate_unit_price(
                p.price, p.container_size, p.container_unit
            )
            if unit_price != p.unit_price or unit_measure != p.unit_measure:
                p.unit_price = unit_price
                p.unit_measure = unit_measure
                p.unit_price_missing = False
                updated += 1
        elif p.price and not p.container_size:
            if not p.unit_price_missing:
                p.unit_price_missing = True
                flagged += 1

    await db.commit()
    return {
        "total": len(prices),
        "updated": updated,
        "flagged_missing": flagged,
    }
