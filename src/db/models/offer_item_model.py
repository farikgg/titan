from decimal import Decimal

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Numeric, ForeignKey, UniqueConstraint

from src.db.initialize import Base


class OfferItemModel(Base):
    __tablename__ = "offer_items"

    id = Column(Integer, primary_key=True)
    offer_id = Column(
        Integer,
        ForeignKey("offers.id", ondelete="CASCADE"),
        index=True
    )

    sku = Column(String(150))
    name = Column(String(255))

    price = Column(Numeric(12, 2))
    quantity = Column(Integer, default=1)
    total = Column(Numeric(12, 2))

    offer = relationship("OfferModel", back_populates="items")

    __table_args__ = (
        UniqueConstraint("offer_id", "sku", name="uq_offer_sku"),
    )
