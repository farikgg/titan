import pytest, pytest_asyncio
from sqlalchemy import select, func, True_
from sqlalchemy.ext.asyncio import async_sessionmaker

# from src.worker.tasks import generate_pdf
from src.db.models.pdf_generation import PdfGeneration
from tests.e2e.test_fuchs_orchestrator import override_async_session


@pytest_asyncio.fixture(autouse=True)
async def override_async_session(monkeypatch, test_engine):
    session_factory = async_sessionmaker(
        test_engine,
        expire_on_commit=False,
    )

    monkeypatch.setattr(
        "src.db.initialize.async_session",
        async_sessionmaker(test_engine, expire_on_commit=False),
    )

    return session_factory


@pytest.mark.asyncio
async def test_generate_pdf_idempotent(monkeypatch, override_async_session):
    pytest.skip("Outdated test, generate_pdf was removed from src.worker.tasks")
    deal_id=111
    stage_id="PAID"

    async def fake_deal(self, deal_id):
        return {
            "ID": deal_id,
            "TITLE": "test_deal",
            "STAGE_ID": stage_id,
            "CURRENCY_ID": "EUR",
        }

    async def fake_product(self, deal_id):
        return [
            {"PRODUCT_ID": "FUCHS-123", "PRICE": 100}
        ]

    async def fake_resolve_prices(self, db, skus, source, force_refresh=False):
        return [
            {
                "art": "FUCHS-123",
                "name": "Oil",
                "price": 100,
                "currency": "EUR",
            }
        ]

    # ---- FAKE PDF ----

    def fake_generate_offer(self, deal):
        return "/tmp/fake.pdf"

    # ---- PATCHES ----

    monkeypatch.setattr(
        "src.services.bitrix_service.BitrixService.get_deal",
        fake_deal,
    )

    monkeypatch.setattr(
        "src.services.bitrix_service.BitrixService.get_deal_products",
        fake_product,
    )

    monkeypatch.setattr(
        "src.services.price_service.PriceService.resolve_prices",
        fake_resolve_prices,
    )

    monkeypatch.setattr(
        "src.services.pdf_service.PdfService.generate_offer",
        fake_generate_offer,
    )

    # ---- FIRST CALL ----
    await generate_pdf(deal_id, stage_id)

    # ---- SECOND CALL (should not duplicate) ----
    await generate_pdf(deal_id, stage_id)

    # ---- CHECK DB ----
    async with override_async_session() as session:
        count = await session.scalar(
            select(func.count(PdfGeneration.id))
        )

    assert count == 1


@pytest.mark.asyncio
async def test_generate_pdf_full_flow(monkeypatch, override_async_session):
    pytest.skip("Outdated test, generate_pdf was removed from src.worker.tasks")
    deal_id = 222
    stage_id = "PAID"

    # ---- FAKE DEAL ----
    async def fake_deal(self, deal_id):
        return {
            "ID": deal_id,
            "TITLE": "Full Flow Deal",
            "STAGE_ID": stage_id,
            "CURRENCY_ID": "EUR",
        }

    async def fake_products(self, deal_id):
        return [
            {"PRODUCT_ID": "FUCHS-123", "PRICE": 100}
        ]

    async def fake_resolve_prices(self, db, skus, source, force_refresh=False):
        return [
            {
                "art": "FUCHS-123",
                "name": "Oil",
                "price": 100,
                "currency": "EUR",
            }
        ]

    def fake_generate_offer(self, deal):
        assert deal["title"] == "Full Flow Deal"
        assert deal["currency"] == "EUR"
        return "/tmp/generated.pdf"

    # ---- PATCHES ----
    monkeypatch.setattr(
        "src.services.bitrix_service.BitrixService.get_deal",
        fake_deal,
    )

    monkeypatch.setattr(
        "src.services.bitrix_service.BitrixService.get_deal_products",
        fake_products,
    )

    monkeypatch.setattr(
        "src.services.price_service.PriceService.resolve_prices",
        fake_resolve_prices,
    )

    monkeypatch.setattr(
        "src.services.pdf_service.PdfService.generate_offer",
        fake_generate_offer,
    )

    # ---- EXECUTION ----
    result = await generate_pdf(deal_id, stage_id)

    assert result == "/tmp/generated.pdf"

    # ---- CHECK DB RECORD ----
    async with override_async_session() as session:
        count = await session.scalar(
            select(func.count(PdfGeneration.id)).where(
                PdfGeneration.deal_id == deal_id
            )
        )

    assert count == 1
