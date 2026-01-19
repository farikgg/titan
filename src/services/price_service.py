from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.schemas.price_schema import PriceCreate
from src.repositories.price_repo import PriceRepository

class PriceService:
    def __init__(self) -> None:
        self.repo = PriceRepository()

    async def add_new_price(self, db: AsyncSession, price_data: PriceCreate):
        # Здесь в будущем будет проверка: если такой артикул есть, обновить цену
        # А пока просто создаем
        return await self.repo.create(db, price_data)

    async def get_prices_list(self, db: AsyncSession):
        return await self.repo.get_all(db)
