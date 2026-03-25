import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.services.requests_pipeline import extract_client_info

@pytest.mark.asyncio
@patch("src.services.requests_pipeline.FuchsAIParser")
async def test_extract_client_info_direct_email(mock_parser_class):
    # Mock AI response
    mock_parser = mock_parser_class.return_value
    mock_parser.client.chat.completions.create = AsyncMock()
    mock_parser.client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content='{"contact_name": "Ivanov", "company_name": "TestCo", "contact_phone": "123", "manager_name": "Mngr"}'))]
    )
    mock_parser.model = "gemini-1.5-flash"

    subject = "Request for offer"
    body = "Hello, I need 10 liters of oil. Best, Ivanov"
    sender = "client@external.com"

    result = await extract_client_info(subject, body, sender)

    assert result["contact_email"] == "client@external.com"
    assert result["manager_email"] is None
    assert result["contact_name"] == "Ivanov"
    assert result["company_name"] == "TestCo"

@pytest.mark.asyncio
@patch("src.services.requests_pipeline.FuchsAIParser")
async def test_extract_client_info_forwarded_email(mock_parser_class):
    # Mock AI response
    mock_parser = mock_parser_class.return_value
    mock_parser.client.chat.completions.create = AsyncMock()
    mock_parser.client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content='{"contact_name": "Original Client", "company_name": "ERG", "contact_phone": "777", "manager_name": "Manager YB"}'))]
    )
    mock_parser.model = "gemini-1.5-flash"

    subject = "Fwd: Urgent request"
    body = """
    From: Manager YB <yb@tpgt-titan.com>
    Date: Thu, 26 Mar 2026
    Subject: Fwd: Request
    
    Check this.
    
    ---------- Пересылаемое сообщение ----------
    От: Original Client <erg.posttorgi@erg.kz>
    Дата: Ср, 25 марта 2026 г. в 10:00
    Тема: Request
    
    I need some items.
    """
    sender = "yb@tpgt-titan.com"

    result = await extract_client_info(subject, body, sender)

    assert result["manager_email"] == "yb@tpgt-titan.com"
    assert result["contact_email"] == "erg.posttorgi@erg.kz"
    assert result["contact_name"] == "Original Client"
    assert result["company_name"] == "ERG"

@pytest.mark.asyncio
@patch("src.services.requests_pipeline.FuchsAIParser")
async def test_extract_client_info_negative_no_client(mock_parser_class):
    # Mock AI response with no data
    mock_parser = mock_parser_class.return_value
    mock_parser.client.chat.completions.create = AsyncMock(side_effect=Exception("AI error"))

    subject = "Internal note"
    body = "This is just a note without client info."
    sender = "internal@tpgt.kz"

    result = await extract_client_info(subject, body, sender)

    # If no external email found, contact_email defaults to sender.
    assert result["contact_email"] == "internal@tpgt.kz"
    assert result["manager_email"] == "internal@tpgt.kz"
    assert result["contact_name"] is None
