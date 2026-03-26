from decimal import Decimal

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Numeric, ForeignKey, UniqueConstraint

from src.db.initialize import Base


class OfferItemModel(Base):
    __tablename__ = "offer_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(
        ForeignKey("offers.id", ondelete="CASCADE"),
        index=True
    )

    sku: Mapped[str] = mapped_column(String(150))
    name: Mapped[str] = mapped_column(String(255))
    raw_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    quantity: Mapped[int] = mapped_column(default=1)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    offer = relationship("OfferModel", back_populates="items")

    __table_args__ = (
        UniqueConstraint("offer_id", "sku", name="uq_offer_sku"),
    )
