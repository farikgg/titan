from sqlalchemy import String, func, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

from src.db.initialize import Base


class PdfGeneration(Base):
    __tablename__ = "pdf_generations"

    id: Mapped[int] = mapped_column(primary_key=True)
    deal_id: Mapped[int] = mapped_column(index=True)
    stage_id: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )