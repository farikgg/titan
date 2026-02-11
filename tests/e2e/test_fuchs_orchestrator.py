import pytest, pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker
from src.repositories.price_repo import PriceRepository
from src.services.fuchs_pipeline import process_fuchs_message

from tests.factories.email_factory import (
    fuchs_email_with_excel,
    fuchs_email_no_excel,
)
from tests.factories.excel_factory import excel_prices
from tests.factories.ai_factory import ai_prices


from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import async_sessionmaker


@pytest_asyncio.fixture(autouse=True)
def override_async_session(monkeypatch, test_engine):
    async_session_factory = async_sessionmaker(
        test_engine, expire_on_commit=False
    )

    @asynccontextmanager
    async def _session():
        async with async_session_factory() as session:
            yield session

    monkeypatch.setattr(
        "src.services.fuchs_pipeline.async_session",
        _session,
    )

    return async_session_factory


@pytest.mark.asyncio
async def test_fuchs_email_with_excel(monkeypatch, override_async_session):
    email = fuchs_email_with_excel()

    monkeypatch.setattr(
        "src.services.excel_parser.FuchsExcelParser.parse",
        lambda *_: excel_prices(),
    )

    monkeypatch.setattr(
        "src.services.fuchs_parser.FuchsAIParser.parse_to_objects",
        lambda *_: pytest.fail("AI should not be called"),
    )

    result = await process_fuchs_message(email)
    assert result.startswith("Сохранено")

    repo = PriceRepository()
    async with override_async_session() as session:
        exists = await repo.exists_by_message_id(session, "msg-1")
        assert exists is True



@pytest.mark.asyncio
async def test_fuchs_email_ai_fallback(monkeypatch, override_async_session):
    email = fuchs_email_no_excel()

    monkeypatch.setattr(
        "src.services.excel_parser.FuchsExcelParser.parse",
        lambda *_: [],
    )

    async def fake_ai_parse(*args, **kwargs):
        return ai_prices()

    monkeypatch.setattr(
        "src.services.fuchs_parser.FuchsAIParser.parse_to_objects",
        lambda *_: fake_ai_parse(),
    )

    result = await process_fuchs_message(email)
    assert result.startswith("Сохранено")

    repo = PriceRepository()
    async with override_async_session() as session:
        exists = await repo.exists_by_message_id(session, "msg-1")
        assert exists is True


@pytest.mark.asyncio
async def test_idempotency(monkeypatch, override_async_session):
    message_id="dup-1"
    email = fuchs_email_with_excel(message_id)

    monkeypatch.setattr(
        "src.services.excel_parser.FuchsExcelParser.parse",
        lambda *_: excel_prices(),
    )

    await process_fuchs_message(email)
    await process_fuchs_message(email)

    repo = PriceRepository()
    async with override_async_session() as session:
        exists = await repo.exists_by_message_id(session, message_id)
        assert exists is True
