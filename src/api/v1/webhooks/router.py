import logging

from fastapi import APIRouter, Request
from src.db.initialize import async_session
from src.db.models.webhook_log import WebhookLog
from src.worker.tasks import process_deal_update

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


async def _parse_bitrix_request(request: Request) -> dict:
    """
    Bitrix24 может слать как JSON, так и form-data.
    Парсим оба варианта.
    """
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        return await request.json()

    # form-data (application/x-www-form-urlencoded) — стандарт Bitrix24
    form = await request.form()
    return dict(form)


async def _handle_bitrix_webhook(request: Request):
    """Общая логика обработки вебхука Bitrix24."""
    payload = await _parse_bitrix_request(request)

    logger.info("Bitrix webhook payload: %s", payload)

    async with async_session() as session:
        session.add(WebhookLog(source="bitrix", payload=payload))
        await session.commit()

    # Bitrix form-data шлёт event и data[FIELDS][ID] в плоском виде
    event = payload.get("event")
    deal_id = (
        payload.get("data", {}).get("FIELDS", {}).get("ID")  # JSON формат
        or payload.get("data[FIELDS][ID]")                    # form-data формат
    )

    logger.info("Bitrix webhook: event=%s, deal_id=%s", event, deal_id)

    if event == "ONCRMDEALUPDATE" and deal_id:
        process_deal_update.delay(deal_id)

    return {"status": "ok"}


@router.post("/bitrix")
async def bitrix_webhook(request: Request):
    return await _handle_bitrix_webhook(request)


@router.post("/bitrix/deals")
async def bitrix_webhook_deals_alias(request: Request):
    """Алиас — Bitrix24 шлёт сюда."""
    return await _handle_bitrix_webhook(request)
