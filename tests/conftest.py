# import sys
# from pathlib import Path
#
# # фикс импорта src
# ROOT = Path(__file__).resolve().parents[1]
# sys.path.insert(0, str(ROOT))
# import pytest_asyncio
# from sqlalchemy.ext.asyncio import (
#     create_async_engine,
#     async_sessionmaker,
#     AsyncSession,
# )
#
# from src.db.initialize import Base
#
# TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
#
#
# @pytest_asyncio.fixture(scope="session")
# async def engine():
#     engine = create_async_engine(TEST_DATABASE_URL, echo=False)
#
#     async with engine.begin() as conn:
#         await conn.run_sync(Base.metadata.create_all)
#
#     yield engine
#
#     await engine.dispose()
#
#
# @pytest_asyncio.fixture
# async def db(engine) -> AsyncSession:
#     async_session = async_sessionmaker(
#         engine, expire_on_commit=False, class_=AsyncSession
#     )
#
#     async with async_session() as session:
#         yield session
#         await session.rollback()
import sys
from pathlib import Path

# 👇 СНАЧАЛА добавляем корень проекта
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from src.db.initialize import Base

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()

@pytest_asyncio.fixture
async def db(test_engine) -> AsyncSession:
    session_factory = async_sessionmaker(
        test_engine,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session
        await session.rollback()

