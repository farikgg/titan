import os
from dotenv import load_dotenv

from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession




load_dotenv('.env')
DATABASE_URL = os.environ.get("DATABASE_URL")

engine = create_async_engine(
    url=DATABASE_URL,
    pool_size=20, # ! maximum amount of sessions, may need to increment it
    max_overflow=10,
    pool_recycle=3600,     
    pool_pre_ping=True    
)

async_session = async_sessionmaker(bind=engine, class_=AsyncSession, autoflush=True, expire_on_commit=False)



class Base(DeclarativeBase):
    '''Базовый класс ОРМ моделек алхимии, от него наследуют таблицы. 
       Позволяет инициализировать бд (смотри setup_database())'''
    pass

# ! REPLACE WITH ALEMBIC----------------------------------------------------
async def setup_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        print('[БД] Инициализирована успешно : схема создана/проверена. REPLACE ME WITH ALEMBIC')
# ! ------------------------------------------------------------------------


async def get_db():
    async with async_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
    