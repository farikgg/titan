from fastapi import APIRouter
from src.db.initialize import async_session
from src.db.models.webhook_log import WebhookLog
from src.worker.tasks import process_deal_update

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/bitrix")
async def bitrix_webhook(payload: dict):
    async with async_session() as session:
        session.add(WebhookLog(source="bitrix", payload=payload))
        await session.commit()

    event = payload.get("event")
    deal_id = payload.get("data", {}).get("FIELDS", {}).get("ID")

    if event == "ONCRMDEALUPDATE":
        process_deal_update.delay(deal_id)

    return {"status": "ok"}
