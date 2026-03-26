from pydantic import BaseModel, ConfigDict
from decimal import Decimal
from datetime import datetime
from typing import Optional

from src.db.models.price_model import Source, SourceType


class PriceBase(BaseModel):
    art: str
    name: str
    raw_name: str | None = None
    description: str | None = None
    price: Decimal | None = None
    quantity: float | None = 1.0
    unit: str | None = None
    currency: str | None = None
    source: Source
    source_type: SourceType
    email_message_id: Optional[str] = None
    # FUCHS validity
    first_seen_at: Optional[datetime] = None
    valid_from: Optional[datetime] = None
    valid_days: Optional[int] = None
    # Unit price (oils / lubricants)
    container_size: Optional[Decimal] = None
    container_unit: Optional[str] = None  # "L", "KG"
    unit_price: Optional[Decimal] = None
    unit_measure: Optional[str] = None  # "per_kg", "per_liter"
    unit_price_missing: Optional[bool] = None

class PriceCreate(PriceBase):
    pass


class PriceRead(PriceBase):
    id: int
    updated_at: datetime
    valid_to: Optional[datetime] = None
    validity_status: Optional[str] = None
    days_left: Optional[int] = None
    # Unit price (calculated) is now inherited from PriceBase
    model_config = ConfigDict(from_attributes=True)
