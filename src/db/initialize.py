import os
from dotenv import load_dotenv

from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession




load_dotenv('.env')
DATABASE_URL = os.environ.get("DATABASE_URL")

engine = create_async_engine(url=DATABASE_URL)
async_session = async_sessionmaker(bind=engine, class_=AsyncSession, autoflush=True, expire_on_commit=False)



class Base(DeclarativeBase):
    '''Базовый класс ОРМ моделек алхимии, от него наследуют таблицы. 
       Позволяет инициализировать бд (смотри setup_database())'''
    pass


async def setup_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        print('[БД] Инициализирована успешно : схема создана/проверена')
        


async def get_db():
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception as err:
            await session.rollback()
            print(f"[БД] Ошибка при создании сессии : {err}")

    