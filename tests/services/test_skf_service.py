import pytest, respx
from httpx import Response

from src.services.skf_service import SKFService


@pytest.mark.asyncio
@respx.mock
async def test_skf_get_price_success():
    service = SKFService()
    sku = "SKF-111-TEST"

    respx.post(service.URL).mock(
        return_value=Response(
            200,
            json={
                "SupplierItemID": sku,
                "QuantityBasedPrice": 2200.00,
                "Currency": "KZT",
                "StockAvailability": ["10"]
            }
        )
    )

    price = await service.get_price(sku)

    assert price is not None
    assert price.art == sku
    assert price.price == 2200.00
    assert price.currency == "KZT"


@pytest.mark.asyncio
@respx.mock
async def test_skf_get_price_with_error_message():
    service = SKFService()
    sku = "SKF-111-TEST"

    respx.post(service.URL).mock(
        return_value=Response(
            200,
            json={"message": "Product not found"}
        )
    )

    price = await service.get_price(sku)

    assert price is None


@pytest.mark.asyncio
@respx.mock
async def test_skf_get_price_missing_fields():
    service = SKFService()
    sku = "SKF-111-TEST"

    respx.post(service.URL).mock(
        return_value=Response(
            200,
            json={"SupplierItemID": sku}
        )
    )

    price = await service.get_price(sku)

    assert price is None
