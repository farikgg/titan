import pytest
import pandas as pd
from unittest.mock import MagicMock, patch
from io import BytesIO
from src.services.fuchs_parser import FuchsAIParser
from src.schemas.extraction_schema import ExtractionResult

def test_extract_text_from_attachments_excel_to_markdown():
    with patch("google.genai.Client"):
        parser = FuchsAIParser()
    
    # Mock data
    mock_df = pd.DataFrame([
        {"Наименование": "Масло Fuchs", "Кол-во": 10, "Ед.изм.": "л"},
        {"Наименование": "Смазка", "Кол-во": 5, "Ед.изм.": "кг"}
    ])
    
    attachments = [
        {"name": "test.xlsx", "content": b"dummy content", "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
    ]
    
    with patch("pandas.read_excel", return_value=mock_df):
        # Mock to_markdown to avoid 'tabulate' dependency issue in tests
        with patch.object(pd.DataFrame, "to_markdown", return_value="| Наименование |   Кол-во | Ед.изм. |"):
            text = parser.extract_text_from_attachments(attachments)
        
    # Check if Markdown table header is in the extracted text
    assert "| Наименование |   Кол-во | Ед.изм. |" in text

def test_extraction_result_pydantic_validation():
    # Test valid JSON response from Gemini
    raw_json = {
        "items": [
            {
                "art": "12345",
                "name": "Fuchs Titan",
                "raw_name": "Titan 5W30",
                "quantity": 30.5,
                "unit": "л",
                "price": 1500.0,
                "currency": "EUR"
            }
        ],
        "payment_terms": "100% предоплата",
        "delivery_terms": "DDP Almaty",
        "warranty_terms": "12 месяцев",
        "dates": ["2026-04-01"]
    }
    
    result = ExtractionResult(**raw_json)
    
    assert len(result.items) == 1
    assert result.items[0].art == "12345"
    assert result.items[0].quantity == 30.5
    assert result.items[0].unit == "л"
    assert result.payment_terms == "100% предоплата"
    assert len(result.dates) == 1
    assert result.dates[0] == "2026-04-01"

@pytest.mark.asyncio
@patch("google.genai.Client")
async def test_gemini_mock_response(mock_client_class):
    parser = FuchsAIParser()
    
    # Mock Response object
    mock_response = MagicMock()
    mock_response.text = '{"items": [{"art": "TEST", "name": "Item", "quantity": 1, "unit": "pcs"}], "dates": []}'
    
    # Setup mock chain
    mock_client = mock_client_class.return_value
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
    
    result = await parser.parse_to_objects("Email body", "Table text")
    
    assert result["items"][0]["art"] == "TEST"
    assert result["items"][0]["quantity"] == 1
    assert result["items"][0]["unit"] == "pcs"

# Add AsyncMock if not imported (it's in unittest.mock)
from unittest.mock import AsyncMock
