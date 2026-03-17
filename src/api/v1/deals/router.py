from fastapi import APIRouter, Depends, HTTPException, Request, Header
from typing import Annotated
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.initialize import get_db
from src.core.bitrix import get_bitrix_client
from src.services.bitrix_service import BitrixService
from src.services.price_service import PriceService
from src.services.deal_service import DealService
from src.core.rbac import require_permission
from src.core.auth import get_tg_user, get_tg_user_or_admin
from src.app.config import settings
from src.app.config import BITRIX_STAGES
from src.db.models.offer_model import OfferModel
from pathlib import Path


router = APIRouter(prefix="/deals", tags=["Deals"])


def _get_deal_service() -> DealService:
    bx = get_bitrix_client()
    return DealService(BitrixService(bx), PriceService())


def _get_bitrix_service() -> BitrixService:
    bx = get_bitrix_client()
    return BitrixService(bx)


async def verify_user_or_admin_token(
    request: Request,
    token: Annotated[str | None, Header()] = None,
):
    """
    Для некоторых ручек (например, комментарии сделки) разрешаем доступ:
      1) либо через X-Telegram-Init-Data (TMA),
      2) либо через ADMIN_SECRET_TOKEN в заголовке `token`.
    """
    x_telegram_init_data = request.headers.get("X-Telegram-Init-Data")
    if x_telegram_init_data:
        return True

    if token and token == settings.ADMIN_SECRET_TOKEN:
        return True

    raise HTTPException(
        status_code=401,
        detail="Unauthorized: need Telegram init data or valid admin token",
    )


# ──────────────────────────────────────────────
#  Создание сделки из Telegram Mini App
# ──────────────────────────────────────────────


class CreateDealRequest(BaseModel):
    title: str
    company_id: int
    contact_id: int | None = None
    stage: str = "NEW"  # NEW / FINAL_INVOICE / EXECUTING / WON / LOSE / APOLOGY / LOSE_REASON_COMPETITOR
    solution: str  # systems_lubrication / lubricant / fire_systems
    amount: float


@router.post(
    "/",
    dependencies=[Depends(require_permission("deals.write"))],
)
async def create_deal(
    body: CreateDealRequest,
    user=Depends(get_tg_user_or_admin),
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
            contact_id=body.contact_id,
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


class CompanyShort(BaseModel):
    id: int
    title: str
    phone: str | None = None
    email: str | None = None


class ContactShort(BaseModel):
    id: int
    name: str
    phone: str | None = None
    email: str | None = None


@router.get(
    "/companies/search",
    dependencies=[Depends(require_permission("deals.write"))],
    response_model=list[CompanyShort],
    summary="Поиск компаний (клиентов) в Bitrix24 по названию",
)
async def search_companies(
    q: str,
    limit: int = 20,
    user=Depends(get_tg_user_or_admin),
):
    """
    Поиск компаний в Bitrix24 для выбора клиента при создании сделки.

    Параметры:
      - q: строка поиска (начало названия или часть слова)
      - limit: максимум результатов (по умолчанию 20)
    """
    bx_service = _get_bitrix_service()
    raw_companies = await bx_service.search_companies(query=q, limit=limit)

    companies: list[CompanyShort] = []
    for c in raw_companies:
        if not isinstance(c, dict):
            continue
        phones = c.get("PHONE") or []
        emails = c.get("EMAIL") or []
        phone = None
        email = None
        if isinstance(phones, list) and phones:
            phone = phones[0].get("VALUE")
        if isinstance(emails, list) and emails:
            email = emails[0].get("VALUE")

        companies.append(
            CompanyShort(
                id=int(c.get("ID")),
                title=c.get("TITLE", ""),
                phone=phone,
                email=email,
            )
        )

    return companies


@router.get(
    "/contacts/search",
    dependencies=[Depends(require_permission("deals.write"))],
    response_model=list[ContactShort],
    summary="Поиск контактов в Bitrix24 по имени (опционально по компании)",
)
async def search_contacts(
    q: str,
    company_id: int | None = None,
    limit: int = 20,
    user=Depends(get_tg_user_or_admin),
):
    """
    Поиск контактов в Bitrix24 для выбора контактного лица при создании сделки.

    Параметры:
      - q: строка поиска по имени/фамилии
      - company_id: если указан — фильтрация по компании
      - limit: максимум результатов (по умолчанию 20)
    """
    bx_service = _get_bitrix_service()
    raw_contacts = await bx_service.search_contacts(
        query=q,
        limit=limit,
        company_id=company_id,
    )

    contacts: list[ContactShort] = []
    for c in raw_contacts:
        if not isinstance(c, dict):
            continue

        first_name = (c.get("NAME") or "").strip()
        last_name = (c.get("LAST_NAME") or "").strip()
        second_name = (c.get("SECOND_NAME") or "").strip()

        # Собираем ФИО
        parts = [p for p in [last_name, first_name, second_name] if p]
        full_name = " ".join(parts) if parts else (first_name or last_name or "")

        phones = c.get("PHONE") or []
        emails = c.get("EMAIL") or []
        phone = None
        email = None
        if isinstance(phones, list) and phones:
            phone = phones[0].get("VALUE")
        if isinstance(emails, list) and emails:
            email = emails[0].get("VALUE")

        contacts.append(
            ContactShort(
                id=int(c.get("ID")),
                name=full_name,
                phone=phone,
                email=email,
            )
        )

    return contacts


@router.get(
    "/",
    dependencies=[Depends(require_permission("deals.read"))],
)
async def list_deals(
    user=Depends(get_tg_user_or_admin),
    stage: str | None = None,  # Фильтр по стадии: NEW, FINAL_INVOICE, EXECUTING, WON, LOSE
    manager_bitrix_id: int | None = None,  # Для руководителей/админов: фильтр по ответственному
):
    import logging
    logger = logging.getLogger(__name__)
    
    user_id = getattr(user, "id", None)
    user_role = getattr(user, "role", None)
    bitrix_user_id = getattr(user, "bitrix_user_id", None)
    
    # Маппинг названий стадий на STAGE_ID
    stage_map = {
        "NEW": BITRIX_STAGES.NEW,
        "FINAL_INVOICE": BITRIX_STAGES.FINAL_INVOICE,
        "EXECUTING": BITRIX_STAGES.EXECUTING,
        "WON": BITRIX_STAGES.WON,
        "LOSE": BITRIX_STAGES.LOSE,
    }
    
    stage_id = None
    if stage:
        stage_id = stage_map.get(stage.upper())
        if not stage_id:
            logger.warning(
                "Deals API: неизвестная стадия '%s', игнорирую фильтр",
                stage,
            )
    
    # Менеджеру нельзя override-ить ответственного — он всегда видит только свои сделки.
    assigned_param = None
    if user_role in ("head-manager", "admin") and manager_bitrix_id:
        assigned_param = manager_bitrix_id

    logger.info(
        "Deals API: запрос списка сделок от пользователя id=%s, role=%s, bitrix_user_id=%s, stage=%s (stage_id=%s), manager_bitrix_id=%s",
        user_id,
        user_role,
        bitrix_user_id,
        stage,
        stage_id,
        assigned_param,
    )
    
    deals = await _get_deal_service().list_deals_for_user(
        user,
        stage_id=stage_id,
        assigned_by_id=assigned_param,
    )
    
    # Безопасная обработка: проверяем, что deals - это список
    if not isinstance(deals, list):
        logger.error(
            "Deals API: list_deals_for_user вернул не список! Тип: %s, значение: %s",
            type(deals),
            deals,
        )
        deals = []
    
    # Безопасное логирование первых 3 сделок
    preview = []
    if deals:
        try:
            preview = [
                {"id": d.get("ID"), "title": d.get("TITLE"), "assigned": d.get("ASSIGNED_BY_ID")}
                for d in deals[:3]
            ]
        except (TypeError, AttributeError, KeyError) as e:
            logger.warning("Deals API: ошибка при формировании preview сделок: %s", e)
            preview = [f"Ошибка: {type(d)}" for d in deals[:3] if deals]
    
    logger.info(
        "Deals API: возвращаю %d сделок для пользователя id=%s (bitrix_user_id=%s). "
        "Первые 3 сделки: %s",
        len(deals),
        user_id,
        bitrix_user_id,
        preview,
    )
    
    return deals


@router.get(
    "/{deal_id}",
    dependencies=[Depends(require_permission("deals.read"))],
)
async def get_deal(
    deal_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_tg_user_or_admin),
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
    user=Depends(get_tg_user_or_admin),
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
    summary="Получить список стадий воронки Гидротех.Сделки",
)
async def get_stages_info():
    """
    Возвращает информацию о стадиях воронки «Гидротех.Сделки».
    Основные стадии (для фильтрации в UI):
    - NEW: Интерес или ТКП
    - FINAL_INVOICE: Договор заключен. В работе
    - EXECUTING: АВР и Накладная подписаны
    - WON: Сделка успешна
    - LOSE: Нет финансирования
    """
    return {
        "pipeline": "Гидротех.Сделки",
        "category_id": BITRIX_STAGES.CATEGORY_ID,
        # Основные стадии для фильтрации (5 штук)
        "main_stages": [
            {
                "key": "NEW",
                "stage_id": BITRIX_STAGES.NEW,
                "name": "Интерес или ТКП",
            },
            {
                "key": "FINAL_INVOICE",
                "stage_id": BITRIX_STAGES.FINAL_INVOICE,
                "name": "Договор заключен. В работе",
            },
            {
                "key": "EXECUTING",
                "stage_id": BITRIX_STAGES.EXECUTING,
                "name": "АВР и Накладная подписаны",
            },
            {
                "key": "WON",
                "stage_id": BITRIX_STAGES.WON,
                "name": "Сделка успешна",
            },
            {
                "key": "LOSE",
                "stage_id": BITRIX_STAGES.LOSE,
                "name": "Нет финансирования",
            },
        ],
        # Все стадии (для справки)
        "all_stages": {
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


# ──────────────────────────────────────────────
#  Прикрепление КП (PDF) к сделке вручную
# ──────────────────────────────────────────────


class AttachKpRequest(BaseModel):
    offer_id: int


@router.post(
    "/{deal_id}/attach-kp",
    dependencies=[Depends(require_permission("deals.write")), Depends(verify_user_or_admin_token)],
    summary="Ручное прикрепление PDF КП к сделке Bitrix24",
)
async def attach_kp_to_deal(
    deal_id: int,
    body: AttachKpRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_tg_user_or_admin),
):
    """
    Ручной сценарий:

    - В TMA уже есть сделка (создана из мини‑апки или почты),
    - Есть сгенерированное КП (offer) с полем pdf_path,
    - Нужно прикрепить это КП к сделке в Bitrix24.

    Требует:
      - deal_id — ID сделки в Bitrix24
      - offer_id — ID оффера в Titan
    """
    # 1. Находим оффер и проверяем наличие PDF
    offer = await db.get(OfferModel, body.offer_id)
    if not offer:
        raise HTTPException(status_code=404, detail=f"Offer {body.offer_id} not found")

    pdf_path_raw = getattr(offer, "pdf_path", None)
    if not pdf_path_raw:
        raise HTTPException(
            status_code=400,
            detail=f"Offer {body.offer_id} has no generated PDF (pdf_path is empty)",
        )

    pdf_path = Path(pdf_path_raw)
    if not pdf_path.exists():
        raise HTTPException(
            status_code=400,
            detail=f"PDF file not found on server: {pdf_path}",
        )

    # 2. Прикрепляем PDF к сделке через BitrixService
    bitrix = _get_bitrix_service()
    ok = await bitrix.attach_kp_pdf(deal_id=deal_id, pdf_path=pdf_path)

    if not ok:
        raise HTTPException(
            status_code=502,
            detail="Failed to attach PDF to deal in Bitrix24",
        )

    return {
        "deal_id": deal_id,
        "offer_id": body.offer_id,
        "attached": True,
    }


# ──────────────────────────────────────────────
#  Комментарии / Чат сделки
# ──────────────────────────────────────────────


class AddCommentRequest(BaseModel):
    text: str
    """Текст сообщения из Telegram Mini App"""


@router.post(
    "/{deal_id}/comments",
    dependencies=[Depends(verify_user_or_admin_token)],
    summary="Отправить сообщение в чат сделки (синхронизация с Bitrix)",
)
async def add_deal_comment(
    deal_id: int,
    body: AddCommentRequest,
    user=Depends(get_tg_user_or_admin),
):
    """
    Добавляет комментарий к сделке в Bitrix24 из Telegram Mini App.
    
    Сообщение, отправленное пользователем в TMA, будет синхронизировано
    в таймлайн сделки в Bitrix24 как комментарий.
    
    Требует:
      - deal_id: ID сделки в Bitrix24
      - text: Текст сообщения
    """
    if not body.text or not body.text.strip():
        raise HTTPException(
            status_code=400,
            detail="Текст сообщения не может быть пустым",
        )
    
    bitrix_service = _get_bitrix_service()
    
    # Получаем bitrix_user_id пользователя для указания автора комментария
    author_id = getattr(user, "bitrix_user_id", None)
    
    # Проверяем, что сделка существует
    deal = await bitrix_service.get_deal(deal_id)
    if not deal:
        raise HTTPException(
            status_code=404,
            detail=f"Сделка {deal_id} не найдена в Bitrix24",
        )
    
    # Добавляем комментарий в Bitrix
    comment_id = await bitrix_service.add_deal_comment(
        deal_id=deal_id,
        text=body.text.strip(),
        author_id=author_id,
    )
    
    if not comment_id:
        raise HTTPException(
            status_code=502,
            detail="Не удалось добавить комментарий в Bitrix24",
        )
    
    return {
        "deal_id": deal_id,
        "comment_id": comment_id,
        "text": body.text.strip(),
        "author_id": author_id,
    }


@router.get(
    "/{deal_id}/comments",
    dependencies=[Depends(verify_user_or_admin_token)],
    summary="Получить комментарии из чата сделки (из Bitrix)",
)
async def get_deal_comments(
    deal_id: int,
    limit: int = 50,
    user=Depends(get_tg_user_or_admin),
):
    """
    Получает комментарии из таймлайна сделки в Bitrix24.
    
    Возвращает список комментариев, отсортированных по дате создания (новые сверху).
    
    Параметры:
      - deal_id: ID сделки в Bitrix24
      - limit: Максимальное количество комментариев (по умолчанию 50)
    """
    bitrix_service = _get_bitrix_service()
    
    # Проверяем, что сделка существует
    deal = await bitrix_service.get_deal(deal_id)
    if not deal:
        raise HTTPException(
            status_code=404,
            detail=f"Сделка {deal_id} не найдена в Bitrix24",
        )
    
    # Получаем комментарии
    comments = await bitrix_service.get_deal_comments(deal_id=deal_id, limit=limit)
    
    return {
        "deal_id": deal_id,
        "comments": comments,
        "total": len(comments),
    }
