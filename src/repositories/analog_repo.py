from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.product_analog_model import ProductAnalogModel


class AnalogRepository:
    async def get_by_source_art(
        self, db: AsyncSession, source_art: str
    ) -> list[ProductAnalogModel]:
        result = await db.execute(
            select(ProductAnalogModel)
            .where(ProductAnalogModel.source_art == source_art)
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
    ) -> ProductAnalogModel:
        obj = ProductAnalogModel(
            source_art=source_art,
            analog_art=analog_art,
            analog_name=analog_name,
            analog_source=analog_source,
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
