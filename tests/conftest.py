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

import os
# Ставим заглушки для обязательных переменных окружения, 
# чтобы pydantic Settings не падал при импорте.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("ADMIN_SECRET_TOKEN", "test-token")
os.environ.setdefault("SKF_API_KEY", "test")
os.environ.setdefault("SKF_API_SECRET", "test")
os.environ.setdefault("SKF_SALES_UNIT_ID", "test")
os.environ.setdefault("SKF_CUSTOMER_ID", "test")
os.environ.setdefault("AZURE_TENANT_ID", "test")
os.environ.setdefault("AZURE_CLIENT_ID", "test")
os.environ.setdefault("AZURE_CLIENT_SECRET", "test")
os.environ.setdefault("GOOGLE_API_KEY", "test-key-for-gemini")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test")
os.environ.setdefault("ANALOG_REQUEST_RECIPIENT", "test@example.com")

import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from src.db.initialize import Base

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL)

    async with engine.begin() as conn:
        import src.db.models
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

