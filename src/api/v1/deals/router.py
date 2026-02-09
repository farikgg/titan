from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.initialize import get_db
from src.core.bitrix import get_bitrix_client
from src.services.bitrix_service import BitrixService
from src.services.price_service import PriceService
from src.services.deal_service import DealService
from src.core.rbac import require_permission
from src.core.auth import get_tg_user



router = APIRouter(prefix="/deals", tags=["Deals"])


@router.get(
    "/",
    dependencies=[Depends(require_permission("deals.read"))],
)
async def list_deals(
    user=Depends(get_tg_user),
):
    bx = get_bitrix_client()
    deal_service = DealService(
        BitrixService(bx),
        PriceService(),
    )
    return await deal_service.list_deals_for_user(user)


@router.get(
    "/{deal_id}",
    dependencies=[Depends(require_permission("deals.read"))],
)
async def get_deal(
    deal_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(),
):
    bx = get_bitrix_client()
    deal_service = DealService(
        BitrixService(bx),
        PriceService(),
    )

    dto = await deal_service.get_deal_dto(
        deal_id=deal_id,
        db=db,
        supplier="fuchs",
    )

    if not dto:
        raise HTTPException(status_code=404, detail="Deal not found")

    return dto
