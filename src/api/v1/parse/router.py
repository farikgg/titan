import logging

from fastapi import APIRouter, Header, Depends, Path, HTTPException, Request
from typing import Annotated, Optional

from celery.result import AsyncResult

from src.worker.celery_app import app
from src.core.exceptions import UserIsNotValidError
from src.app.config import settings
from src.services.lock_service import LockService
from src.core.auth import get_tg_user
from src.db.models.user_model import UserModel
from src.db.initialize import get_db
from sqlalchemy.ext.asyncio import AsyncSession

lock_service = LockService()

logger = logging.getLogger(__name__)

router = APIRouter( prefix='/sync-now',
                     tags=["Sync Now"] )


async def verify_user_or_telegram(
        request: Request,
        token: Annotated[str | None, Header()] = None,
        db: AsyncSession = Depends(get_db),
):
    """
    Проверяет авторизацию через токен или Telegram.
    Возвращает True, если авторизация успешна.
    """
    # Сначала пробуем Telegram auth
    try:
        x_telegram_init_data = request.headers.get("X-Telegram-Init-Data")
        if x_telegram_init_data:
            from src.core.auth import verify_telegram_data
            # Пробуем оба токена
            tokens_to_try = []
            if settings.TELEGRAM_TMA_BOT_TOKEN:
                tokens_to_try.append(settings.TELEGRAM_TMA_BOT_TOKEN)
            tokens_to_try.append(settings.TELEGRAM_BOT_TOKEN)
            
            for bot_token in tokens_to_try:
                try:
                    verify_telegram_data(x_telegram_init_data, bot_token)
                    return True
                except ValueError:
                    continue
    except Exception:
        pass
    
    # Если Telegram не сработал, пробуем токен
    if token and token == settings.ADMIN_SECRET_TOKEN:
        return True
    
    raise HTTPException(status_code=401, detail="Unauthorized: Need Telegram auth or valid token")

@router.post("/", responses=dict())
async def sync_now(
        _: bool = Depends(verify_user_or_telegram),
):
    """
    Запускает парсинг FUCHS из почты.
    Поддерживает два способа авторизации:
    1. Через Telegram (X-Telegram-Init-Data header) - для фронта
    2. Через токен (token header) - для админов
    """
    # Пытаемся взять замок на процесс парсинга Fuchs
    if not await lock_service.acquire_lock("fuchs_sync", expire=600):
        raise HTTPException(status_code=429, detail="Синхронизация уже запущена. Подождите 10 минут.")

    from src.worker.tasks import parse_from_fuchs
    task = parse_from_fuchs.delay()
    return {"task_id": task.id, "status": "queued"}


@router.get("/status/{task_id}", responses=dict())
async def get_status(
        task_id: Annotated[str,
        Path(description="ID Celery таска")],
        _: bool = Depends(verify_user_or_telegram),
):
    """
    Возвращает статус Celery-задачи.

    ВАЖНО: в текущей конфигурации Celery backend отключен (DisabledBackend),
    поэтому мы не можем получить реальный статус задачи из хранилища результатов.
    Эндпоинт работает в "best-effort" режиме:
      - если backend когда-нибудь будет включён, вернёт реальный статус;
      - если backend отключён, вернёт статус "unknown".
    """
    try:
        # Пытаемся получить статус из Celery (если когда-нибудь включим backend)
        res = AsyncResult(task_id, app=app)

        response = {
            "task_id": task_id,
            "status": res.state,
            "result": None,
        }

        if res.ready():
            # если задача завершена, возвращаем результат (то, что вернул return в task)
            response["result"] = res.result if res.successful() else str(res.result)

        return response

    except AttributeError as e:
        # Сюда попадаем при DisabledBackend (как в нынешней конфигурации)
        logger.warning(
            "Celery backend is disabled, cannot fetch task status for %s: %s",
            task_id,
            e,
        )
        return {
            "task_id": task_id,
            "status": "unknown",
            "result": None,
        }
