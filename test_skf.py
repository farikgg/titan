import asyncio, httpx
from datetime import datetime, timedelta


async def test_skf():
    url = "https://api.skf.com/PnA/v1/PriceCheck"
    headers = {
        "apikey": "mGBqosUa7w9wchqsht11O1X50JtWm8sp",  # Твой ключ
        "Content-Type": "application/json"
    }
    payload = {
        "SalesUnitID": "72735",
        "CustomerID": "w199",
        "OrderType": "03",
        "SupplierItemID": "085734",  # Артикул насоса
        "PackageCode": "12",
        "RequiredDate": (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"),
        "RequiredQuantity": "1"
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload, headers=headers)
        print(f"Status: {resp.status_code}")
        print(f"Body: {resp.text}")


if __name__ == "__main__":
    asyncio.run(test_skf())