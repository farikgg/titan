from pydantic import BaseModel, ConfigDict
from decimal import Decimal
from datetime import datetime
from typing import Optional

from src.db.models.price import Source, SourceType


class PriceBase(BaseModel):
    art: str
    name: str
    description: str | None = None
    price: Decimal
    currency: str
    source: Source
    source_type: SourceType
    email_message_id: Optional[str] = None


class PriceCreate(PriceBase):
    pass


class PriceRead(PriceBase):
    id: int
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
