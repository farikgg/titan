import logging

from fastapi import APIRouter, Header, Depends, Path, HTTPException
from typing import Annotated

from celery.result import AsyncResult

from src.worker.celery_app import app
from src.core.exceptions import UserIsNotValidError
from src.app.config import settings
from src.services.lock_service import LockService

lock_service = LockService()

logger = logging.getLogger(__name__)

router = APIRouter( prefix='/sync-now',
                     tags=["Sync Now"] )


async def verify_user(
        token: Annotated[str | None,
        Header()] = None
):
    if token != settings.ADMIN_SECRET_TOKEN:
        raise UserIsNotValidError()
    return token

@router.post("/", responses=dict())
async def sync_now(
        token: Annotated[str,
        Depends(verify_user)]
):
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
        token: Annotated[str, Depends(verify_user)] = None
):
    # Создаем объект результата
    res = AsyncResult(task_id, app=app)

    response = {
        "task_id": task_id,
        "status": res.state,
        "result": None
    }

    if res.ready():
        # если задача завершена, возвращаем результат (то, что вернул return в task)
        response["result"] = res.result if res.successful() else str(res.result)

    return response
