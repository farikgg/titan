import httpx, logging
from datetime import datetime, timedelta

from src.app.config import settings
from src.schemas.price_schema import PriceCreate
from src.db.models.price_model import Source, SourceType

logger = logging.getLogger(__name__)


class SKFService:
    URL = "https://skf-api-external-eu20-tyvvw4iy.prod.apimanagement.eu20.hana.ondemand.com:443/PnA/PriceCheck"

    async def get_price(self, sku: str) -> PriceCreate | None:
        payload = {
            "SalesUnitID": settings.SKF_SALES_UNIT_ID,
            "CustomerID": settings.SKF_CUSTOMER_ID,
            "OrderType": "03",
            "SupplierItemID": sku,
            "PackageCode": "12",
            "RequiredDate": (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%d"),
            "RequiredQuantity": "1",
        }

        async with httpx.AsyncClient(
            headers={
                "apiKey": settings.SKF_API_KEY,
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(40.0, connect=10.0),
        ) as client:
            try:
                resp = await client.post(self.URL, json=payload)
                resp.raise_for_status()
                data = resp.json()

                if data.get("message"):
                    logger.error("SKF API error", extra={"sku": sku, "msg": data["message"]})
                    return None

                price = data.get("QuantityBasedPrice")
                currency = data.get("Currency")

                if price is None or currency is None:
                    return None

                return PriceCreate(
                    art=sku,
                    name=data.get("SupplierItemID", sku),
                    price=price,
                    currency=currency,
                    description=str(data.get("StockAvailability")),
                    source=Source.SKF,
                    source_type=SourceType.API,
                )

            except Exception as e:
                logger.exception("SKF request failed", extra={"sku": sku})
                return None
