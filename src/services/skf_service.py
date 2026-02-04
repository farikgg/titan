import httpx, logging
from datetime import datetime, timedelta

from src.app.config import settings
from src.schemas.price_schema import PriceCreate

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
            timeout=10.0,
        ) as client:
            try:
                resp = await client.post(self.URL, json=payload)
                data = resp.json()

                if data.get("message"):
                    logger.error("SKF API error", extra={"sku": sku, "msg": data["message"]})
                    return None

                return PriceCreate(
                    art=sku,
                    name=data.get("SupplierItemID", sku),
                    price=data.get("QuantityBasedPrice"),
                    currency=data.get("Currency"),
                    description=str(data.get("StockAvailability")),
                    source="skf",
                    source_type="api",
                )

            except Exception as e:
                logger.exception("SKF request failed", extra={"sku": sku})
                return None
