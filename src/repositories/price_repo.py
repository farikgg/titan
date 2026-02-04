from sqlalchemy import select, exists
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.price import PriceModel
from src.schemas.price_schema import PriceCreate


class PriceRepository:
    async def create(self, db: AsyncSession, price_in: PriceCreate) -> PriceModel:
        # 1. Превращаем Pydantic схему в словарь
        data = price_in.model_dump()
        # 2. Создаем экземпляр модели БД
        db_obj = PriceModel(**data)
        try:
        # 3. Добавляем в сессию
            db.add(db_obj)
        # 5. Обновляем объект, чтобы получить ID и updated_at из БД
            await db.refresh(db_obj)
            return db_obj
        except IntegrityError:
            await db.rollback()
            raise

    async def get_all(self, db: AsyncSession) -> list[PriceModel]:
        # Делаем select(PriceModel) и возвращаем результаты
        query = select(PriceModel).order_by(PriceModel.updated_at.desc())
        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_by_art(self, db: AsyncSession, sku: str) -> PriceModel:
        query = (
            select(PriceModel).
            where(PriceModel.art == sku).
            order_by(PriceModel.updated_at.desc())
        )
        result = await db.execute(query)
        return result.scalars().first()

    async def get_by_arts(self, db: AsyncSession, skus: list[str]) -> list[PriceModel]:
        if not skus:
            return []
        query = (
            select(PriceModel).
            where(PriceModel.art.in_(skus)).
            order_by(PriceModel.updated_at.desc())
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    async def exists_by_message_id(self, db: AsyncSession, message_id: str) -> bool:
        """
        проверка письма в БД, чтобы избежать дублирования
        добработка Идемпотентности
        """
        if not message_id:
            return False

        # испльзуем exists() для быстрого поиска
        query = select(exists().where(PriceModel.email_message_id == message_id))
        result = await db.execute(query)
        return result.scalar()

    async def update(self, db: AsyncSession, db_data: PriceModel, obj_in: PriceCreate) -> PriceModel:
        update_data = obj_in.model_dump(exclude_unset=True)
        for field in update_data:
            setattr(db_data, field, update_data[field])

        db.add(db_data)
        await db.commit()
        await db.refresh(db_data)
        return db_data
