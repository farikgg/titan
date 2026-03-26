import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Mapped, relationship, mapped_column
from sqlalchemy import Column, String, Numeric, Enum, ForeignKey, func, Text, Boolean, Integer, DateTime

from src.db.initialize import Base


class OfferStatus(enum.Enum):
    DRAFT = "draft"
    GENERATED = "generated"
    SENT = "sent"
    CONVERTED = "converted"


class OfferModel(Base):
    __tablename__ = "offers"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)

    status = Column(
        Enum(OfferStatus),
        default=OfferStatus.DRAFT,
        nullable=False,
    )

    total = Column(Numeric(12, 2), default=0)
    bitrix_deal_id = Column(String(50), nullable=True)

    created_at = Column(
        DateTime, server_default=func.now()
    )
    is_generating = Column(Boolean, default=False)
    pdf_path = Column(String(255), nullable=True)

    items = relationship(
        "OfferItemModel",
        back_populates="offer",
        cascade="all, delete-orphan"
    )
    currency = Column(String(3), nullable=True)

    # Текстовые условия КП (могут быть NULL)
    payment_terms = Column(Text, nullable=True)
    delivery_terms = Column(Text, nullable=True)
    warranty_terms = Column(Text, nullable=True)

    # Новые поля для шапки запроса
    manager_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    incoterms: Mapped[str | None] = mapped_column(String(100), nullable=True)
    deadline: Mapped[str | None] = mapped_column(String(100), nullable=True)
    delivery_place: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Флаг, включает ли итоговая цена НДС.
    # Используется, в частности, для отображения/скрытия подписи «(без НДС)» в PDF.
    vat_enabled = Column(Boolean, nullable=True)
