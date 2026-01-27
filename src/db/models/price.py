import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Numeric, Enum, func, Text

from src.db.initialize import Base

class Source(enum.Enum):
    FUCHS = "fuchs"
    SKF = "skf"

class SourceType(enum.Enum):
    EMAIL = "email"
    API = "api"

class PriceModel(Base):
    __tablename__ = "prices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email_message_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    art: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    source: Mapped[Source] = mapped_column(Enum(Source))
    source_type: Mapped[SourceType] = mapped_column(Enum(SourceType))
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
