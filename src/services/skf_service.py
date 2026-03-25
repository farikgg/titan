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

        timeout = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)

        async with httpx.AsyncClient(
            headers={
                "apiKey": settings.SKF_API_KEY,
                "Accept": "application/json",
            },
            timeout=timeout,
        ) as client:

            logger.info("SKF request", extra={"sku": sku, "payload": payload})

            try:
                resp = await client.post(self.URL, json=payload)
                resp.raise_for_status()

                logger.info(
                    "SKF response",
                    extra={
                        "sku": sku,
                        "status": resp.status_code,
                        "body": resp.text[:500],
                    },
                )

                data = resp.json()

                if data.get("message"):
                    logger.error("SKF API error", extra={"sku": sku, "api_msg": data["message"]})
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

            except httpx.ReadTimeout:
                logger.warning("SKF timeout", extra={"sku": sku})
                raise

            except httpx.HTTPStatusError as e:
                logger.error("SKF HTTP error", extra={
                    "sku": sku,
                    "status": e.response.status_code,
                    "body": e.response.text,
                })
                raise

            except Exception:
                logger.exception("Unexpected SKF failure", extra={"sku": sku})
                raise
