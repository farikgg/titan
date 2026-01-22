import logging

from fastapi import APIRouter, Header, Depends, Path
from typing import Annotated

from celery.result import AsyncResult

from src.worker.celery_app import app
from src.worker.tasks import parse_from_fuchs
from src.core.exceptions import UserIsNotValidError
from src.app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter( prefix='/sync-now',
                     tags=["Sync Now"] )


async def verify_user(token: Annotated[str | None, Header()] = None):
    if token != settings.ADMIN_SECRET_TOKEN:
        raise UserIsNotValidError()
    return token

@router.post("/", responses=dict())
async def sync_now(token: Annotated[str, Depends(verify_user)]):
    logger.info(f"Токен верный, token: {token}")
    task = parse_from_fuchs.delay()
    return {"task_id": task.id, "status": "queued"}


@router.get("/status/{task_id}", responses=dict())
async def get_status(task_id: Annotated[str, Path(description="ID Celery таска")],
                     token: Annotated[str, Depends(verify_user)] = None):
    # Создаем объект результата
    res = AsyncResult(task_id, app=app)

    response = {
        "task_id": task_id,
        "status": res.state,
        "result": None
    }

    if res.ready():
        # если задача завершена, возвращаем результат (то, что вернул return в task)
        response["result"] = res.result() if res.successful() else str(res.result)

    return response