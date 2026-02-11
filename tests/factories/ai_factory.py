# tests/factories/ai_factory.py

from src.schemas.price_schema import Source, SourceType, PriceCreate


def ai_prices():
    return [
        PriceCreate(
            art="AI-456",
            name="Grease X",
            price=123.45,
            currency="EUR",
            source=Source.FUCHS,
            source_type=SourceType.EMAIL,
        )
    ]
