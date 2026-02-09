from sqlalchemy import JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

from src.db.initialize import Base


class WebhookLog(Base):
    __tablename__ = "webhook_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50))  # bitrix
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now()
    )
