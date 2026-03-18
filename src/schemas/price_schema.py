from pydantic import BaseModel, ConfigDict
from decimal import Decimal
from datetime import datetime
from typing import Optional

from src.db.models.price_model import Source, SourceType


class PriceBase(BaseModel):
    art: str
    name: str
    description: str | None = None
    price: Decimal | None = None
    currency: str | None = None
    source: Source
    source_type: SourceType
    email_message_id: Optional[str] = None
    # FUCHS validity
    first_seen_at: Optional[datetime] = None
    valid_from: Optional[datetime] = None
    valid_days: Optional[int] = None


class PriceCreate(PriceBase):
    pass


class PriceRead(PriceBase):
    id: int
    updated_at: datetime
    valid_to: Optional[datetime] = None
    validity_status: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
