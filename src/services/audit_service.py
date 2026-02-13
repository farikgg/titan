from src.db.models.audit_log import AuditLog

class AuditService:

    def __init__(self, db):
        self.db = db

    async def log(self, actor_type: str, actor_id: int | None, action: str, payload: dict):

        log = AuditLog(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            payload=payload,
        )

        self.db.add(log)
        await self.db.flush()
