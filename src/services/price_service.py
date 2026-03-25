import logging
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Iterable

from src.schemas.price_schema import PriceCreate
from src.repositories.price_repo import PriceRepository
from src.core.exceptions import PriceDoesNotExists
from src.db.models.price_model import Source

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
            # first_seen_at: сохраняем дату первого появления артикула
            # valid_from: дата начала действия текущей цены
            valid_from = getattr(price_data, "valid_from", None)
            first_seen = getattr(existing, "first_seen_at", None)
            if valid_from:
                if first_seen is None or valid_from < first_seen:
                    # если это самое раннее письмо — фиксируем
                    price_data = price_data.model_copy(update={"first_seen_at": valid_from})
                else:
                    # иначе сохраняем существующее
                    price_data = price_data.model_copy(update={"first_seen_at": first_seen})
            else:
                # если дата не передана — не трогаем первое появление
                price_data = price_data.model_copy(update={"first_seen_at": first_seen})

            # valid_days: если не передали — ставим дефолт 90
            if getattr(price_data, "valid_days", None) is None:
                price_data = price_data.model_copy(update={"valid_days": 90})

            # Unit price: пересчитываем если есть данные по таре
            price_data = self._enrich_unit_price(price_data)

            return await self.repo.update(db, existing, price_data)

        # Новая запись — тоже считаем unit_price
        price_data = self._enrich_unit_price(price_data)
        return await self.repo.create(db, price_data)

    @staticmethod
    def calculate_unit_price(
        price: "Decimal | float | None",
        container_size: "Decimal | float | None",
        container_unit: str | None,
    ) -> tuple["Decimal | None", str | None]:
        """
        Рассчитать цену за единицу (кг/литр).

        Пример:
            price=501, container_size=200, container_unit="L"
            → (Decimal('2.505'), 'per_liter')

        Returns:
            (unit_price, unit_measure) или (None, None)
        """
        from decimal import Decimal as D

        if not price or not container_size:
            return None, None

        price_d = D(str(price))
        size_d = D(str(container_size))

        if size_d <= 0:
            return None, None

        unit_price = (price_d / size_d).quantize(D("0.0001"))

        unit_measure_map = {
            "L": "per_liter",
            "KG": "per_kg",
        }
        unit_measure = unit_measure_map.get(
            (container_unit or "").upper().strip(), "per_unit"
        )
        return unit_price, unit_measure

    @classmethod
    def _enrich_unit_price(cls, price_data: PriceCreate) -> PriceCreate:
        """
        Если есть container_size/container_unit — считаем unit_price.
        Если данных по таре нет — ставим unit_price_missing=True.
        """
        container_size = getattr(price_data, "container_size", None)
        container_unit = getattr(price_data, "container_unit", None)
        price_val = getattr(price_data, "price", None)

        unit_price, unit_measure = cls.calculate_unit_price(
            price_val, container_size, container_unit
        )

        updates = {}
        if unit_price is not None:
            updates["unit_price"] = unit_price
            updates["unit_measure"] = unit_measure
            updates["unit_price_missing"] = False
        elif price_val and not container_size:
            # Цена есть, но данных по таре нет → флаг для ручной проверки
            updates["unit_price_missing"] = True

        if updates:
            # Сохраняем существующие значения если не перезаписываем
            price_data = price_data.model_copy(update=updates)

        return price_data

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