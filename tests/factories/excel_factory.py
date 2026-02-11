# tests/factories/excel_factory.py

from src.schemas.price_schema import PriceCreate
from src.db.models.price import Source, SourceType


def excel_prices():
    return [
        PriceCreate(
            art="FUCHS-123",
            name="Oil 5W30",
            price=100.0,
            currency="EUR",
            source=Source.FUCHS,
            source_type=SourceType.EMAIL,
        )
    ]
