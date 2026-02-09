import pytest
from decimal import Decimal
from src.schemas.price_schema import PriceCreate
from src.db.models.price import Source, SourceType
from src.repositories.price_repo import PriceRepository

@pytest.mark.asyncio
async def test_create_and_get_price(db):
    repo = PriceRepository()

    price = PriceCreate(
        art="TEST-123",
        name="Test Oil",
        price=Decimal("100.50"),
        currency="EUR",
        source=Source.FUCHS,
        source_type=SourceType.EMAIL,
    )

    created = await repo.create(db, price)
    await db.commit()

    fetched = await repo.get_by_art(db, "TEST-123")

    assert fetched is not None
    assert fetched.art == "TEST-123"
    assert fetched.price == Decimal("100.50")

#     тест на идемпотентность
@pytest.mark.asyncio
async def test_exists_by_message_id(db):
    repo = PriceRepository()

    price = PriceCreate(
        art="MAIL-1",
        name="Mail Price",
        price=Decimal("50"),
        currency="EUR",
        source=Source.FUCHS,
        source_type=SourceType.EMAIL,
        email_message_id="<msg-123>",
    )

    await repo.create(db, price)
    await db.commit()

    exists = await repo.exists_by_message_id(db, "<msg-123>")
    assert exists is True
