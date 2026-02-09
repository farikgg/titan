from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.initialize import get_db
from src.schemas.price_schema import PriceCreate, PriceRead
from src.services.price_service import PriceService
from src.core.rbac import require_permission

router = APIRouter(prefix="/prices", tags=["Prices"])
price_service = PriceService()


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
