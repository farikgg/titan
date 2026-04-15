import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.analog_ai_search import AnalogAISearch
from src.db.models.price_model import PriceModel, Source

@pytest.mark.asyncio
async def test_search_not_found_no_candidates(db: AsyncSession):
    """Если в базе нет кандидатов, должен возвращать not_found."""
    search_service = AnalogAISearch()
    # db уже очищена фикстурой в conftest
    
    result = await search_service.search(db, "Test Product", "TEST-001")
    
    assert result["status"] == "not_found"
    assert "Нет кандидатов" in result["reason"]

@pytest.mark.asyncio
async def test_search_auto_found(db: AsyncSession):
    """Если AI нашел аналог с высоким score, статус должен быть auto."""
    search_service = AnalogAISearch()
    
    # Добавляем кандидата в БД
    candidate = PriceModel(
        art="ANA-001",
        name="Analog Product",
        source=Source.FUCHS,
        price=100.0,
        currency="KZT",
        source_type="api"
    )
    db.add(candidate)
    await db.commit()
    
    mock_ai_response = {
        "found": True,
        "analog_product_code": "ANA-001",
        "analog_product_name": "Analog Product",
        "analog_brand": "FUCHS",
        "score": 0.95,
        "reason": "Perfect match",
        "match_type": "exact_code"
    }
    
    with patch.object(search_service, "_get_candidates", return_value=[
        {"code": "ANA-001", "name": "Analog Product", "brand": "FUCHS", "specs": ""}
    ]):
        with patch.object(search_service, "_call_gemini", return_value=mock_ai_response):
            result = await search_service.search(db, "Source Product", "SRC-001", "FUCHS")

    assert result["status"] == "auto"
    assert result["analog_product_code"] == "ANA-001"
    assert result["score"] == 0.95

@pytest.mark.asyncio
async def test_search_suggest_found(db: AsyncSession):
    """score 0.75 → статус suggest."""
    search_service = AnalogAISearch()

    mock_ai_response = {
        "found": True,
        "analog_product_code": "ANA-002",
        "analog_product_name": "Maybe Analog",
        "analog_brand": "SKF",
        "score": 0.75,
        "reason": "Likely match",
        "match_type": "functional"
    }

    with patch.object(search_service, "_get_candidates", return_value=[
        {"code": "ANA-002", "name": "Maybe Analog", "brand": "SKF", "specs": ""}
    ]):
        with patch.object(search_service, "_call_gemini", return_value=mock_ai_response):
            result = await search_service.search(db, "Source Product", "SRC-002", "SKF")

    assert result["status"] == "suggest"
    assert result["score"] == 0.75

@pytest.mark.asyncio
async def test_call_gemini_parsing():
    """Проверка парсинга JSON из ответа Gemini."""
    service = AnalogAISearch()

    mock_response = MagicMock()
    mock_response.text = '{"found": true, "score": 0.9, "analog_product_code": "X1"}'

    # Мокаем asyncio.to_thread правильно — он должен вернуть корутину
    async def fake_to_thread(fn, *args, **kwargs):
        return mock_response

    with patch("src.services.analog_ai_search.asyncio.to_thread", side_effect=fake_to_thread):
        result = await service._call_gemini("name", "code", "brand", "specs", [])

    assert result["found"] is True
    assert result["score"] == 0.9
    assert result["analog_product_code"] == "X1"
