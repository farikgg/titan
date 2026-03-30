from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.product_analog_model import ProductAnalogModel
from src.db.models.analog_request_model import AnalogRequestModel


class AnalogRepository:

    async def get_confirmed_by_source_code(
        self, db: AsyncSession, source_product_code: str
    ) -> list[ProductAnalogModel]:
        """Ищет подтверждённые аналоги по артикулу исходного товара."""
        result = await db.execute(
            select(ProductAnalogModel)
            .where(
                ProductAnalogModel.source_product_code == source_product_code,
                ProductAnalogModel.status == "confirmed",
            )
            .order_by(ProductAnalogModel.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_source_art(
        self, db: AsyncSession, source_art: str
    ) -> list[ProductAnalogModel]:
        """Обратная совместимость: поиск по source_product_code (любой статус)."""
        result = await db.execute(
            select(ProductAnalogModel)
            .where(ProductAnalogModel.source_product_code == source_art)
            .order_by(ProductAnalogModel.created_at.desc())
        )
        return list(result.scalars().all())

    async def create(
        self,
        db: AsyncSession,
        source_art: str,
        analog_art: str,
        analog_name: str | None = None,
        analog_source: str | None = None,
        notes: str | None = None,
        *,
        source_product_name: str | None = None,
        source_brand: str | None = None,
        analog_brand: str | None = None,
        match_type: str | None = None,
        confidence_level: float | None = None,
        status: str = "new",
        added_from: str | None = None,
        email_thread_id: str | None = None,
        confirmed_by: int | None = None,
    ) -> ProductAnalogModel:
        obj = ProductAnalogModel(
            source_product_code=source_art,
            source_product_name=source_product_name,
            source_brand=source_brand,
            supplier_name=analog_source,
            analog_product_code=analog_art,
            analog_product_name=analog_name,
            analog_brand=analog_brand,
            match_type=match_type,
            confidence_level=confidence_level,
            status=status,
            added_from=added_from,
            email_thread_id=email_thread_id,
            confirmed_by=confirmed_by,
            notes=notes,
        )
        db.add(obj)
        await db.flush()
        await db.refresh(obj)
        return obj

    async def delete_by_id(self, db: AsyncSession, analog_id: int) -> bool:
        result = await db.execute(
            delete(ProductAnalogModel).where(ProductAnalogModel.id == analog_id)
        )
        return result.rowcount > 0


class AnalogRequestRepository:

    async def create(
        self,
        db: AsyncSession,
        *,
        product_code: str | None = None,
        product_name: str | None = None,
        brand: str | None = None,
        supplier: str | None = None,
        deal_id: str | None = None,
        client_id: str | None = None,
        manager_id: int | None = None,
        request_status: str = "pending",
    ) -> AnalogRequestModel:
        obj = AnalogRequestModel(
            product_code=product_code,
            product_name=product_name,
            brand=brand,
            supplier=supplier,
            deal_id=deal_id,
            client_id=client_id,
            manager_id=manager_id,
            request_status=request_status,
        )
        db.add(obj)
        await db.flush()
        await db.refresh(obj)
        return obj

    async def get_pending(self, db: AsyncSession) -> list[AnalogRequestModel]:
        result = await db.execute(
            select(AnalogRequestModel)
            .where(AnalogRequestModel.request_status == "pending")
            .order_by(AnalogRequestModel.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_deal_id(
        self, db: AsyncSession, deal_id: str
    ) -> list[AnalogRequestModel]:
        result = await db.execute(
            select(AnalogRequestModel)
            .where(AnalogRequestModel.deal_id == deal_id)
            .order_by(AnalogRequestModel.created_at.desc())
        )
        return list(result.scalars().all())
