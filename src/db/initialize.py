import logging
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession, create_async_engine

from src.app.config import settings


logger = logging.getLogger(__name__)

engine_kwargs = {
    "url": settings.DATABASE_URL,
    "pool_recycle": 3600,
    "pool_pre_ping": True,
}

# SQLite не поддерживает pool_size и max_overflow
if not settings.DATABASE_URL.startswith("sqlite"):
    engine_kwargs["pool_size"] = 20
    engine_kwargs["max_overflow"] = 10

engine = create_async_engine(**engine_kwargs)

async_session = async_sessionmaker(bind=engine, class_=AsyncSession, autoflush=True, expire_on_commit=False)

class Base(DeclarativeBase):
    '''
    Базовый класс ОРМ моделек алхимии, от него наследуют таблицы. Позволяет инициализировать бд
   '''
    pass

async def get_db():
    '''
    Инжектор сессий ДБ, автоматом закрывает сессют после завершения запроса
    '''
    async with async_session() as session:
        try:
            yield session
        except Exception as e:
            logger.error(f"Проблема в БД: {e}")
            await session.rollback()
            raise
        finally:
            await session.close()
