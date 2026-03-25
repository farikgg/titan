from sqlalchemy import Column, String, func, Integer, DateTime
from sqlalchemy.orm import Mapped
from datetime import datetime

from src.db.initialize import Base


class PdfGeneration(Base):
    __tablename__ = "pdf_generations"

    id = Column(Integer, primary_key=True)
    deal_id = Column(Integer, index=True)
    stage_id = Column(String(50))
    created_at = Column(
        DateTime, server_default=func.now()
    )