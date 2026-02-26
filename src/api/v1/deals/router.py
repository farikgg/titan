from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.initialize import get_db
from src.core.bitrix import get_bitrix_client
from src.services.bitrix_service import BitrixService
from src.services.price_service import PriceService
from src.services.deal_service import DealService
from src.core.rbac import require_permission
from src.core.auth import get_tg_user
from src.app.config import BITRIX_STAGES


router = APIRouter(prefix="/deals", tags=["Deals"])


def _get_deal_service() -> DealService:
    bx = get_bitrix_client()
    return DealService(BitrixService(bx), PriceService())


@router.get(
    "/",
    dependencies=[Depends(require_permission("deals.read"))],
)
async def list_deals(
    user=Depends(get_tg_user),
):
    return await _get_deal_service().list_deals_for_user(user)


@router.get(
    "/{deal_id}",
    dependencies=[Depends(require_permission("deals.read"))],
)
async def get_deal(
    deal_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_tg_user),
):
    dto = await _get_deal_service().get_deal_dto(
        deal_id=deal_id,
        db=db,
        supplier="fuchs",
    )

    if not dto:
        raise HTTPException(status_code=404, detail="Deal not found")

    return dto


# ──────────────────────────────────────────────
#  Смена стадий сделки
# ──────────────────────────────────────────────


class StageTransitionRequest(BaseModel):
    stage: str


@router.post(
    "/{deal_id}/stage",
    dependencies=[Depends(require_permission("deals.write"))],
    summary="Сменить стадию сделки в воронке Гидротех",
)
async def change_deal_stage(
    deal_id: int,
    body: StageTransitionRequest,
    user=Depends(get_tg_user),
):
    deal_service = _get_deal_service()

    stage_map = {
        "preparation": deal_service.move_to_preparation,
        "kp_created": deal_service.move_to_kp_created,
        "kp_sent": deal_service.move_to_kp_sent,
        "won": deal_service.move_to_won,
        "lost": deal_service.move_to_lost,
    }

    handler = stage_map.get(body.stage.lower())
    if not handler:
        raise HTTPException(
            status_code=400,
            detail=f"Неизвестная стадия: {body.stage}. Допустимые: {list(stage_map.keys())}",
        )

    success = await handler(deal_id)
    if not success:
        raise HTTPException(
            status_code=409,
            detail="Переход стадии невозможен. Проверьте текущую стадию сделки.",
        )

    return {"deal_id": deal_id, "new_stage": body.stage}


@router.get(
    "/stages/info",
    summary="Получить список стадий воронки Гидротех",
)
async def get_stages_info():
    return {
        "pipeline": "Гидротех",
        "category_id": BITRIX_STAGES.CATEGORY_ID,
        "stages": {
            "NEW": BITRIX_STAGES.NEW,
            "PREPARATION": BITRIX_STAGES.PREPARATION,
            "KP_CREATED": BITRIX_STAGES.KP_CREATED,
            "KP_SENT": BITRIX_STAGES.KP_SENT,
            "WON": BITRIX_STAGES.WON,
            "LOSE": BITRIX_STAGES.LOSE,
        },
        "transitions": BITRIX_STAGES.allowed_transitions,
    }
