import enum
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Numeric, Enum, func, Text, UniqueConstraint, DateTime, Integer

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
    email_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    art: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    source: Mapped[Source] = mapped_column(Enum(Source))
    source_type: Mapped[SourceType] = mapped_column(Enum(SourceType))
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    # --- FUCHS price validity tracking ---
    # first_seen_at: дата первого письма/первого появления артикула (не меняется назад)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    # valid_from: дата начала действия текущей цены (дата получения письма/обновления)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    # valid_days: срок действия цены (по умолчанию 90)
    valid_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="90")

    __table_args__ = (
        UniqueConstraint("art", "source", name="uq_price_art_source"),
    )

    @property
    def valid_to(self) -> datetime | None:
        if not self.valid_from:
            return None
        days = int(self.valid_days or 90)
        return self.valid_from + timedelta(days=days)

    @property
    def validity_status(self) -> str:
        """
        Возвращает статус цены:
          - 'unknown' (если нет valid_from)
          - 'valid'
          - 'expiring_soon' (<= 7 дней до конца)
          - 'expired'
        """
        if not self.valid_from:
            return "unknown"
        vt = self.valid_to
        if not vt:
            return "unknown"
        now = datetime.utcnow()
        if now > vt:
            return "expired"
        if (vt - now).days <= 7:
            return "expiring_soon"
        return "valid"

    @property
    def days_left(self) -> int | None:
        """
        Сколько дней осталось до истечения valid_to.
        Если нет valid_from — возвращаем None.
        """
        if not self.valid_from:
            return None
        vt = self.valid_to
        if not vt:
            return None
        now = datetime.utcnow()
        if now > vt:
            return 0
        return (vt - now).days

class EmailProcessing(Base):
    __tablename__ = "email_processing"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now()
    )
