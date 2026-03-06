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


# ──────────────────────────────────────────────
#  Создание сделки из Telegram Mini App
# ──────────────────────────────────────────────


class CreateDealRequest(BaseModel):
    title: str
    company_id: int
    stage: str = "NEW"  # NEW / FINAL_INVOICE / EXECUTING / WON / LOSE / APOLOGY / LOSE_REASON_COMPETITOR
    solution: str  # systems_lubrication / lubricant / fire_systems
    amount: float


@router.post(
    "/",
    dependencies=[Depends(require_permission("deals.write"))],
)
async def create_deal(
    body: CreateDealRequest,
    user=Depends(get_tg_user),
):
    """
    Создать сделку в воронке «Гидротех.Сделки» из Telegram Mini App.

    Требуемые поля:
      - title: название сделки
      - company_id: ID компании в Bitrix24
      - stage: ключ стадии (NEW / FINAL_INVOICE / EXECUTING / WON / LOSE / APOLOGY / LOSE_REASON_COMPETITOR)
      - solution: ключ решения (systems_lubrication / lubricant / fire_systems)
      - amount: сумма сделки (из КП)
    """
    stage_key = body.stage.upper()
    stage_map = {
        "NEW": BITRIX_STAGES.NEW,
        "FINAL_INVOICE": BITRIX_STAGES.FINAL_INVOICE,
        "EXECUTING": BITRIX_STAGES.EXECUTING,
        "WON": BITRIX_STAGES.WON,
        "LOSE": BITRIX_STAGES.LOSE,
        "APOLOGY": BITRIX_STAGES.APOLOGY,
        "LOSE_REASON_COMPETITOR": BITRIX_STAGES.LOSE_REASON_COMPETITOR,
    }

    stage_id = stage_map.get(stage_key)
    if not stage_id:
        raise HTTPException(
            status_code=400,
            detail=f"Неизвестная стадия: {body.stage}. Допустимые: {list(stage_map.keys())}",
        )

    if not getattr(user, "bitrix_user_id", None):
        raise HTTPException(
            status_code=400,
            detail="У пользователя не задан bitrix_user_id. Обнови профиль пользователя в Битрикс/БД.",
        )

    service = _get_deal_service()
    try:
        deal_id = await service.create_deal_from_miniapp(
            title=body.title,
            company_id=body.company_id,
            stage_id=stage_id,
            solution_code=body.solution,
            amount=body.amount,
            assigned_by_id=user.bitrix_user_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not deal_id:
        raise HTTPException(
            status_code=502,
            detail="Не удалось создать сделку в Bitrix24",
        )

    return {"deal_id": deal_id}


@router.get(
    "/",
    dependencies=[Depends(require_permission("deals.read"))],
)
async def list_deals(
    user=Depends(get_tg_user),
):
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(
        "Deals API: запрос списка сделок от пользователя id=%s, role=%s, bitrix_user_id=%s",
        getattr(user, "id", None),
        getattr(user, "role", None),
        getattr(user, "bitrix_user_id", None),
    )
    
    deals = await _get_deal_service().list_deals_for_user(user)
    
    logger.info(
        "Deals API: возвращаю %d сделок для пользователя id=%s",
        len(deals),
        getattr(user, "id", None),
    )
    
    return deals


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
        "pipeline": "Гидротех.Сделки",
        "category_id": BITRIX_STAGES.CATEGORY_ID,
        "stages": {
            "NEW": BITRIX_STAGES.NEW,
            "FINAL_INVOICE": BITRIX_STAGES.FINAL_INVOICE,
            "EXECUTING": BITRIX_STAGES.EXECUTING,
            "WON": BITRIX_STAGES.WON,
            "LOSE": BITRIX_STAGES.LOSE,
            "APOLOGY": BITRIX_STAGES.APOLOGY,
            "LOSE_REASON_COMPETITOR": BITRIX_STAGES.LOSE_REASON_COMPETITOR,
        },
        "transitions": BITRIX_STAGES.allowed_transitions,
    }
