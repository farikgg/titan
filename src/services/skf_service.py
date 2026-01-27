import httpx, logging

from datetime import datetime, timedelta

from src.app.config import settings
from src.schemas.price_schema import PriceCreate

logger = logging.getLogger(__name__)


class SKFService:
    def __init__(self):
        self.url = "https://skf-api-external-eu20-tyvwv4iy.prod.apimanagement.eu20.hana.ondemand.com:443/PnA/PriceCheck"
        # Создаем клиент один раз при инициализации сервиса
        self.client = httpx.AsyncClient(
            headers={
                "apiKey": settings.SKF_API_KEY,
                "Accept": "application/json"
            },
            timeout=10.0
        )

    async def get_price(self, sku: str) -> PriceCreate | None:
        payload = {
            "SalesUnitID": settings.SKF_SALES_UNIT_ID,
            "CustomerID": settings.SKF_CUSTOMER_ID,
            "OrderType": "03",
            "SupplierItemID": sku,
            "PackageCode": "12",
            "RequiredDate": (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"),
            "RequiredQuantity": "1"
        }

        try:
            response = await self.client.post(self.url, json=payload)
            # Если SKF вернул ошибку, но статус 200 (как на скрине)
            data = response.json()
            if data.get("message"):
                logger.error(f"SKF API Error: {data.get('message')}")
                return None

            # Маппинг данных в нашу схему
            return PriceCreate(
                art=sku,
                name=data.get("SupplierItemID", sku),  # или дозапрос в Product Info API
                price=data.get("QuantityBasedPrice"),
                currency=data.get("Currency"),
                description=f"Stock: {data.get('StockAvailability', [])}",
                source="skf",
                source_type="api"
            )
        except Exception as e:
            logger.error(f"Ошибка при запросе к SKF: {e}")
            return None
