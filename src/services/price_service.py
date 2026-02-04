import logging
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Iterable

from src.schemas.price_schema import PriceCreate
from src.repositories.price_repo import PriceRepository
from src.core.exceptions import PriceDoesNotExists
from src.db.models.price import Source

logger = logging.getLogger(__name__)

STALE_HOURS = 24


class PriceService:
    def __init__(self) -> None:
        self.repo = PriceRepository()

    async def add_new_price(self, db: AsyncSession, price_data: PriceCreate):
        # Здесь в будущем будет проверка: если такой артикул есть, обновить цену
        # А пока просто создаем
        return await self.repo.create(db, price_data)

    async def get_prices_list(self, db: AsyncSession):
        return await self.repo.get_all(db)

    async def get_price(self, db: AsyncSession, art_id: str):
        art_id = art_id.strip() # очищаем от ебучих пробелов чтобы код не падал на этом этапе
        price = await self.repo.get_by_art(db, art_id) # art_id change to skus

        if not price:
            raise PriceDoesNotExists()

        if price.source == Source.SKF:
            if datetime.now() - price.updated_at.replace(tzinfo=None) > timedelta(hours=24):
                from src.worker.tasks import sync_skf_single
                sync_skf_single.delay(price.art)
                logger.info(f"Запущено фоновое обновление для {price.art}")
        return price

    async def update_or_create(self, db: AsyncSession, price_data: PriceCreate):
        """
        Используется ТОЛЬКО из Celery / mail pipeline
        """
        existing = await self.repo.get_by_art(db, price_data.art)
        if existing:
            return await self.repo.update(db, existing, price_data)
        return await self.repo.create(db, price_data)

    async def resolve_prices(self, db: AsyncSession, skus: Iterable[str], source: str, force_refresh: bool = False):
        # нормализуем письма
        skus = self._normalize_skus(skus)
        if not skus:
            return []

        # берем данные из БД
        prices = await self.repo.get_by_arts(db, skus)
        found_map = {p.art: p for p in prices}
        missing = [s for s in skus if s not in found_map]

        # stale check
        stale = self._detect_stale(prices)

        if missing or stale or force_refresh:
            self._enqueue_background_sync(missing, stale, source)

        return prices

    def _normalize_skus(self, skus: Iterable[str]) -> list[str]:
        return sorted(
            {sku.strip().upper() for sku in skus if sku and sku.strip()}
        )

    def _detect_stale(self, prices) -> list[str]:
        stale = []
        now = datetime.utcnow()

        for price in prices:
            if price.source != Source.SKF:
                continue

            updated_at = price.updated_at.replace(tzinfo=None)
            if now - updated_at > timedelta(hours=STALE_HOURS):
                stale.append(price.art)

        return stale

    def _enqueue_background_sync(
        self,
        missing: list[str],
        stale: list[str],
        source: str,
    ):
        """
        Никакой async тут.
        Это orchestration, не выполнение.
        """
        skus = list(set(missing + stale))
        if not skus:
            return

        logger.info(
            "Enqueue price sync",
            extra={"skus": skus, "source": source},
        )

        from src.worker.tasks import sync_skf_bulk
        sync_skf_bulk.delay(skus)