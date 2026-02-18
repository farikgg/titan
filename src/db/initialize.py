import logging
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession, create_async_engine

from src.app.config import settings


logger = logging.getLogger(__name__)

engine = create_async_engine(
    url=settings.DATABASE_URL,
    pool_size=20, # ! maximum amount of sessions, may need to increment it
    max_overflow=10,
    pool_recycle=3600,
    pool_pre_ping=True
)

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
