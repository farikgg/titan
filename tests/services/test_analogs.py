"""
Тесты для модуля аналогов:
- AnalogRepository (CRUD + поиск)
- AnalogRequestRepository (pending, create)
- normalize_code (утилита)
- AnalogParser.parse_analog_reply (с моком Gemini)
- confirm_analog endpoint (роутер)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.analog_repo import AnalogRepository, AnalogRequestRepository, normalize_code
from src.db.models.product_analog_model import ProductAnalogModel
from src.db.models.analog_request_model import AnalogRequestModel


# ══════════════════════════════════════════════════════════════
# 1. UNIT — normalize_code
# ══════════════════════════════════════════════════════════════

def test_normalize_code_removes_spaces():
    assert normalize_code("ABC 123") == "ABC123"

def test_normalize_code_removes_dashes():
    assert normalize_code("ABC-123") == "ABC123"

def test_normalize_code_removes_underscores():
    assert normalize_code("ABC_123") == "ABC123"

def test_normalize_code_uppercases():
    assert normalize_code("abc123") == "ABC123"

def test_normalize_code_mixed():
    assert normalize_code("skf- 6205 _2rs") == "SKF62052RS"

def test_normalize_code_empty():
    assert normalize_code("") == ""

def test_normalize_code_none():
    assert normalize_code(None) == ""


# ══════════════════════════════════════════════════════════════
# 2. INTEGRATION — AnalogRepository (SQLite in-memory через conftest)
# ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_analog(db: AsyncSession):
    repo = AnalogRepository()
    analog = await repo.create(
        db,
        source_art="SKF-6205",
        analog_art="NSK-6205",
        analog_name="NSK Deep Groove Ball Bearing 6205",
        analog_source="NSK",
        status="confirmed",
        confidence_level=0.95,
    )
    await db.commit()

    assert analog.id is not None
    assert analog.source_product_code == "SKF-6205"
    assert analog.analog_product_code == "NSK-6205"
    assert analog.status == "confirmed"
    assert analog.confidence_level == 0.95


@pytest.mark.asyncio
async def test_get_confirmed_by_source_code(db: AsyncSession):
    repo = AnalogRepository()
    await repo.create(db, source_art="FUCHS-001", analog_art="MOB-001", status="confirmed")
    await repo.create(db, source_art="FUCHS-001", analog_art="CAS-001", status="new")  # не confirmed
    await db.commit()

    results = await repo.get_confirmed_by_source_code(db, "FUCHS-001")

    assert len(results) == 1
    assert results[0].analog_product_code == "MOB-001"


@pytest.mark.asyncio
async def test_get_all_for_product_by_code(db: AsyncSession):
    repo = AnalogRepository()
    await repo.create(db, source_art="SKF-6206", analog_art="FAG-6206", status="confirmed")
    await db.commit()

    results = await repo.get_all_for_product(db, code="SKF-6206", name=None)

    assert any(r.analog_product_code == "FAG-6206" for r in results)


@pytest.mark.asyncio
async def test_get_all_for_product_by_name(db: AsyncSession):
    repo = AnalogRepository()
    await repo.create(
        db,
        source_art="FUCHS-TITAN-5W40",
        analog_art="MOB-SYNT-5W40",
        source_product_name="Fuchs Titan GT1 5W-40",
        status="confirmed",
    )
    await db.commit()

    results = await repo.get_all_for_product(db, code=None, name="Titan GT1")

    assert len(results) >= 1
    assert results[0].source_product_name is not None
    assert "Titan" in results[0].source_product_name


@pytest.mark.asyncio
async def test_get_all_for_product_empty_params(db: AsyncSession):
    repo = AnalogRepository()
    results = await repo.get_all_for_product(db, code=None, name=None)
    assert results == []


@pytest.mark.asyncio
async def test_get_all_for_product_returns_only_confirmed(db: AsyncSession):
    repo = AnalogRepository()
    await repo.create(db, source_art="TEST-999", analog_art="ANA-999", status="new")
    await db.commit()

    results = await repo.get_all_for_product(db, code="TEST-999", name=None)
    assert results == []


@pytest.mark.asyncio
async def test_delete_by_id(db: AsyncSession):
    repo = AnalogRepository()
    analog = await repo.create(db, source_art="DEL-001", analog_art="DEL-ANA-001", status="confirmed")
    await db.commit()

    deleted = await repo.delete_by_id(db, analog.id)
    assert deleted is True

    # Повторное удаление — должен вернуть False
    deleted_again = await repo.delete_by_id(db, analog.id)
    assert deleted_again is False


@pytest.mark.asyncio
async def test_get_by_source_art_any_status(db: AsyncSession):
    repo = AnalogRepository()
    await repo.create(db, source_art="MULTI-001", analog_art="A1", status="new")
    await repo.create(db, source_art="MULTI-001", analog_art="A2", status="confirmed")
    await db.commit()

    results = await repo.get_by_source_art(db, "MULTI-001")
    codes = [r.analog_product_code for r in results]
    assert "A1" in codes
    assert "A2" in codes


# ══════════════════════════════════════════════════════════════
# 3. INTEGRATION — AnalogRequestRepository
# ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_analog_request(db: AsyncSession):
    repo = AnalogRequestRepository()
    req = await repo.create(
        db,
        product_code="SKF-UNKNOWN",
        product_name="SKF Unknown Bearing",
        brand="SKF",
        supplier="NSK",
        deal_id="DEAL-123",
        manager_id=42,
    )
    await db.commit()

    assert req.id is not None
    assert req.request_status == "pending"
    assert req.product_code == "SKF-UNKNOWN"
    assert req.manager_id == 42


@pytest.mark.asyncio
async def test_get_pending_returns_only_pending(db: AsyncSession):
    repo = AnalogRequestRepository()
    await repo.create(db, product_code="P1", request_status="pending")
    await repo.create(db, product_code="P2", request_status="resolved")
    await repo.create(db, product_code="P3", request_status="pending")
    await db.commit()

    pending = await repo.get_pending(db)
    statuses = [r.request_status for r in pending]
    assert all(s == "pending" for s in statuses)
    codes = [r.product_code for r in pending]
    assert "P1" in codes
    assert "P3" in codes
    assert "P2" not in codes


@pytest.mark.asyncio
async def test_get_by_deal_id(db: AsyncSession):
    repo = AnalogRequestRepository()
    await repo.create(db, product_code="X1", deal_id="DEAL-777")
    await repo.create(db, product_code="X2", deal_id="DEAL-777")
    await repo.create(db, product_code="X3", deal_id="DEAL-888")
    await db.commit()

    results = await repo.get_by_deal_id(db, "DEAL-777")
    assert len(results) == 2
    codes = [r.product_code for r in results]
    assert "X1" in codes
    assert "X2" in codes


# ══════════════════════════════════════════════════════════════
# 4. UNIT — AnalogParser (мок Gemini)
# ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_parse_analog_reply_success():
    """ИИ успешно извлёк аналог из письма."""
    from src.services.analog_parser import AnalogParser

    mock_response = MagicMock()
    mock_response.text = '{"source_product_code": "SKF-6205", "analog_product_code": "NSK-6205", "analog_product_name": "NSK 6205 ZZ", "analog_brand": "NSK", "confidence_level": 0.92, "notes": "Прямая замена"}'

    with patch("src.services.analog_parser.genai.Client") as MockClient:
        mock_client_instance = MockClient.return_value
        mock_client_instance.models.generate_content.return_value = mock_response

        parser = AnalogParser()
        result = await parser.parse_analog_reply(
            email_body="Предлагаем замену: NSK 6205 ZZ, артикул NSK-6205.",
            subject="Re: Запрос аналога SKF-6205"
        )

    assert result["analog_product_code"] == "NSK-6205"
    assert result["analog_brand"] == "NSK"
    assert result["confidence_level"] == 0.92


@pytest.mark.asyncio
async def test_parse_analog_reply_no_analog():
    """Поставщик отказал — аналогов нет."""
    from src.services.analog_parser import AnalogParser

    mock_response = MagicMock()
    mock_response.text = '{"analog_product_code": null}'

    with patch("src.services.analog_parser.genai.Client") as MockClient:
        MockClient.return_value.models.generate_content.return_value = mock_response

        parser = AnalogParser()
        result = await parser.parse_analog_reply(
            email_body="К сожалению, аналогов нет в наличии.",
            subject="Re: Запрос аналога"
        )

    assert result.get("analog_product_code") is None


@pytest.mark.asyncio
async def test_parse_analog_reply_invalid_json():
    """Gemini вернул мусор — должен вернуть пустой dict."""
    from src.services.analog_parser import AnalogParser

    mock_response = MagicMock()
    mock_response.text = "Извините, не могу обработать запрос."

    with patch("src.services.analog_parser.genai.Client") as MockClient:
        MockClient.return_value.models.generate_content.return_value = mock_response

        parser = AnalogParser()
        result = await parser.parse_analog_reply("body", "subject")

    assert result == {}


@pytest.mark.asyncio
async def test_parse_analog_reply_strips_markdown():
    """Gemini обернул JSON в маркдаун — должен корректно распарсить."""
    from src.services.analog_parser import AnalogParser

    mock_response = MagicMock()
    mock_response.text = '```json\n{"analog_product_code": "FAG-6205", "analog_brand": "FAG", "confidence_level": 0.88, "notes": "", "analog_product_name": "FAG 6205"}\n```'

    with patch("src.services.analog_parser.genai.Client") as MockClient:
        MockClient.return_value.models.generate_content.return_value = mock_response

        parser = AnalogParser()
        result = await parser.parse_analog_reply("body", "subject")

    assert result["analog_product_code"] == "FAG-6205"


@pytest.mark.asyncio
async def test_process_analog_reply_saves_to_db(db: AsyncSession):
    """process_analog_reply создаёт запись в БД со статусом new."""
    from src.services.analog_parser import AnalogParser

    mock_response = MagicMock()
    mock_response.text = '{"source_product_code": "SKF-6205", "analog_product_code": "NTN-6205", "analog_product_name": "NTN 6205", "analog_brand": "NTN", "confidence_level": 0.9, "notes": ""}'

    with patch("src.services.analog_parser.genai.Client") as MockClient:
        MockClient.return_value.models.generate_content.return_value = mock_response

        parser = AnalogParser()
        result = await parser.process_analog_reply(db, {
            "subject": "Re: Запрос аналога: SKF 6205 (art: SKF-6205)",
            "body": "Предлагаем NTN-6205.",
            "message_ids": "MSG-001"
        })

    assert result is not None
    assert result.status == "new"
    assert result.analog_product_code == "NTN-6205"
    assert result.source_product_code == "SKF-6205"


@pytest.mark.asyncio
async def test_process_analog_reply_extracts_source_art_from_subject(db: AsyncSession):
    """Если ИИ не вернул source_product_code, достаём артикул из темы."""
    from src.services.analog_parser import AnalogParser

    mock_response = MagicMock()
    # ИИ не вернул source_product_code
    mock_response.text = '{"analog_product_code": "NTN-6206", "analog_product_name": "NTN 6206", "analog_brand": "NTN", "confidence_level": 0.85, "notes": ""}'

    with patch("src.services.analog_parser.genai.Client") as MockClient:
        MockClient.return_value.models.generate_content.return_value = mock_response

        parser = AnalogParser()
        result = await parser.process_analog_reply(db, {
            "subject": "Re: Запрос аналога (art: SKF-6206)",
            "body": "Предлагаем NTN-6206.",
            "message_ids": "MSG-002"
        })

    assert result.source_product_code == "SKF-6206"


@pytest.mark.asyncio
async def test_process_analog_reply_no_analog_returns_none(db: AsyncSession):
    """Если аналог не найден — process_analog_reply возвращает None."""
    from src.services.analog_parser import AnalogParser

    mock_response = MagicMock()
    mock_response.text = '{"analog_product_code": null}'

    with patch("src.services.analog_parser.genai.Client") as MockClient:
        MockClient.return_value.models.generate_content.return_value = mock_response

        parser = AnalogParser()
        result = await parser.process_analog_reply(db, {
            "subject": "Re: Запрос аналога",
            "body": "Аналогов нет.",
            "message_ids": "MSG-003"
        })

    assert result is None


# ══════════════════════════════════════════════════════════════
# 5. UNIT — Router: confirm_analog (мок db и user)
# ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_confirm_analog_sets_status_confirmed(db: AsyncSession):
    """confirm_analog меняет статус new → confirmed и ставит confirmed_by."""
    from src.api.v1.analogs.router import confirm_analog

    repo = AnalogRepository()
    analog = await repo.create(
        db,
        source_art="CONF-001",
        analog_art="CONF-ANA-001",
        status="new",
    )
    await db.commit()

    class FakeUser:
        id = 99

    result = await confirm_analog(analog.id, db=db, user=FakeUser())
    await db.commit()

    assert result["status"] == "success"
    assert result["analog_id"] == analog.id

    # Проверяем в БД
    from sqlalchemy import select
    updated = await db.scalar(
        select(ProductAnalogModel).where(ProductAnalogModel.id == analog.id)
    )
    assert updated.status == "confirmed"
    assert updated.confirmed_by == 99


@pytest.mark.asyncio
async def test_confirm_analog_not_found_raises_404(db: AsyncSession):
    """confirm_analog возвращает 404 если запись не найдена."""
    from src.api.v1.analogs.router import confirm_analog
    from fastapi import HTTPException

    class FakeUser:
        id = 1

    with pytest.raises(HTTPException) as exc_info:
        await confirm_analog(analog_id=99999, db=db, user=FakeUser())

    assert exc_info.value.status_code == 404