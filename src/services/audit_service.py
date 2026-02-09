from src.db.models.audit_log import AuditLog

class AuditService:
    @staticmethod
    async def log(session, action: str, payload: dict, actor_id=None):
        session.add(
            AuditLog(
                actor_type="user" if actor_id else "system",
                actor_id=actor_id,
                action=action,
                payload=payload,
            )
        )
        await session.commit()
