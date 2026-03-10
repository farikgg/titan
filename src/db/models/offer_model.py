import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Numeric, Enum, ForeignKey, func

from src.db.initialize import Base


class OfferStatus(enum.Enum):
    DRAFT = "draft"
    GENERATED = "generated"
    SENT = "sent"
    CONVERTED = "converted"


class OfferModel(Base):
    __tablename__ = "offers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    status: Mapped[OfferStatus] = mapped_column(
        Enum(OfferStatus),
        default=OfferStatus.DRAFT,
        nullable=False,
    )

    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    bitrix_deal_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now()
    )
    is_generating: Mapped[bool] = mapped_column(default=False)
    pdf_path: Mapped[str | None] = mapped_column(String(255), nullable=True)

    items = relationship(
        "OfferItemModel",
        back_populates="offer",
        cascade="all, delete-orphan"
    )
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
