from sqlalchemy import String, JSON, func
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

from src.db.initialize import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_type: Mapped[str] = mapped_column(String(20))  # user / system
    actor_id: Mapped[int | None]
    action: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now()
    )