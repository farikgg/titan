"""
Тесты для fuchs_pipeline: проверяем, что распарсенный JSON
конвертируется в PriceModel и сохраняется через session.
"""

import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from src.schemas.price_schema import PriceCreate
from src.db.models.price_model import PriceModel, Source, SourceType


class TestPriceCreateMapping:
    """Проверяем, что AI JSON корректно маппится в PriceCreate."""

    def test_basic_mapping(self):
        raw = {
            "art": "TITAN-5W30",
            "name": "FUCHS TITAN GT1 PRO C3 5W-30",
            "raw_name": "Titan GT1 PRO C3 5W-30",
            "description": "Synthetic engine oil",
            "price": 501.0,
            "quantity": 1.0,
            "unit": "шт",
            "currency": "EUR",
            "container_size": 200,
            "container_unit": "L",
            "source": "fuchs",
            "source_type": "email",
        }
        item = PriceCreate(**raw)

        assert item.art == "TITAN-5W30"
        assert item.price == Decimal("501.0")
        assert item.currency == "EUR"
        assert item.source == Source.FUCHS
        assert item.source_type == SourceType.EMAIL
        assert item.container_size == Decimal("200")
        assert item.container_unit == "L"

    def test_mapping_without_optional_fields(self):
        raw = {
            "art": "RENOLIN-B10",
            "name": "RENOLIN B 10",
            "price": 120.50,
            "source": "fuchs",
            "source_type": "email",
        }
        item = PriceCreate(**raw)

        assert item.art == "RENOLIN-B10"
        assert item.price == Decimal("120.50")
        assert item.container_size is None
        assert item.container_unit is None
        assert item.email_message_id is None

    def test_mapping_with_none_price_is_allowed(self):
        raw = {
            "art": "TEST-ART",
            "name": "Test item",
            "price": None,
            "source": "fuchs",
            "source_type": "email",
        }
        item = PriceCreate(**raw)
        assert item.price is None


class TestPriceCreateToPriceModel:
    """Проверяем, что PriceCreate.model_dump() создаёт валидный PriceModel."""

    def test_model_dump_creates_valid_price_model(self):
        item = PriceCreate(
            art="FUCHS-001",
            name="FUCHS Oil",
            price=Decimal("250.00"),
            currency="EUR",
            source=Source.FUCHS,
            source_type=SourceType.EMAIL,
            email_message_id="msg-abc-123",
            valid_days=90,
        )

        data = item.model_dump()
        db_obj = PriceModel(**data)

        assert db_obj.art == "FUCHS-001"
        assert db_obj.price == Decimal("250.00")
        assert db_obj.email_message_id == "msg-abc-123"
        assert db_obj.source == Source.FUCHS
        assert db_obj.source_type == SourceType.EMAIL
        assert db_obj.valid_days == 90


@pytest.mark.asyncio
async def test_process_fuchs_message_saves_to_db():
    """
    End-to-end мок: проверяем, что process_fuchs_message
    вызывает update_or_create и session.commit для каждого товара.
    """
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    ai_items = {
        "items": [
            {
                "art": "ART-001",
                "name": "Oil 1",
                "price": 100.0,
                "currency": "EUR",
            },
            {
                "art": "ART-002",
                "name": "Oil 2",
                "price": 200.0,
                "currency": "EUR",
            },
        ],
        "dates": [],
    }

    msg_dict = {
        "message_ids": "test-msg-id-001",
        "receivedDateTime": "2026-03-18T04:08:09Z",
        "subject": "Test Price List",
        "body": "Price list body",
        "attachments": [],
    }

    with (
        patch("src.services.fuchs_pipeline.FuchsAIParser") as MockAIParser,
        patch("src.services.fuchs_pipeline.PriceService") as MockPriceService,
        patch("src.services.fuchs_pipeline.PriceRepository") as MockPriceRepo,
        patch("src.services.fuchs_pipeline.TelegramService") as MockTg,
        patch("src.services.fuchs_pipeline.get_admin_chat_ids", return_value=[]),
        patch("src.services.fuchs_pipeline.async_session", return_value=mock_session),
    ):
        # AI parser setup
        parser_inst = MockAIParser.return_value
        parser_inst.is_not_spam.return_value = True
        parser_inst.extract_text_from_attachments.return_value = ""
        parser_inst.parse_to_objects = AsyncMock(return_value=ai_items)

        # Repo: message not processed yet
        repo_inst = MockPriceRepo.return_value
        repo_inst.exists_by_message_id = AsyncMock(return_value=False)

        # Price service: track calls
        price_svc_inst = MockPriceService.return_value
        price_svc_inst.update_or_create = AsyncMock()

        from src.services.fuchs_pipeline import process_fuchs_message

        result = await process_fuchs_message(msg_dict)

        # Проверяем, что update_or_create вызван 2 раза (2 товара)
        assert price_svc_inst.update_or_create.call_count == 2

        # Проверяем, что session.commit() был вызван
        mock_session.commit.assert_awaited_once()

        # Проверяем, что результат содержит "Saved: 2"
        assert "Saved: 2" in result

        # Проверяем, что каждый item получил email_message_id
        for call_args in price_svc_inst.update_or_create.call_args_list:
            item = call_args[0][1]  # второй позиционный аргумент
            assert item.email_message_id == "test-msg-id-001"


@pytest.mark.asyncio
async def test_process_fuchs_message_db_error_logged():
    """
    Проверяем, что при ошибке БД pipeline не падает,
    а логирует ошибку через logger.error.
    """
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    ai_items = {
        "items": [
            {"art": "ART-ERR", "name": "Bad item", "price": 50.0, "currency": "EUR"},
        ],
        "dates": [],
    }

    msg_dict = {
        "message_ids": "test-msg-err",
        "receivedDateTime": "2026-03-18T04:08:09Z",
        "subject": "Test",
        "body": "Body",
        "attachments": [],
    }

    with (
        patch("src.services.fuchs_pipeline.FuchsAIParser") as MockAIParser,
        patch("src.services.fuchs_pipeline.PriceService") as MockPriceService,
        patch("src.services.fuchs_pipeline.PriceRepository") as MockPriceRepo,
        patch("src.services.fuchs_pipeline.TelegramService"),
        patch("src.services.fuchs_pipeline.get_admin_chat_ids", return_value=[]),
        patch("src.services.fuchs_pipeline.async_session", return_value=mock_session),
        patch("src.services.fuchs_pipeline.logger") as mock_logger,
    ):
        parser_inst = MockAIParser.return_value
        parser_inst.is_not_spam.return_value = True
        parser_inst.extract_text_from_attachments.return_value = ""
        parser_inst.parse_to_objects = AsyncMock(return_value=ai_items)

        repo_inst = MockPriceRepo.return_value
        repo_inst.exists_by_message_id = AsyncMock(return_value=False)

        # Имитируем ошибку при сохранении
        price_svc_inst = MockPriceService.return_value
        price_svc_inst.update_or_create = AsyncMock(
            side_effect=Exception("UNIQUE constraint failed")
        )

        from src.services.fuchs_pipeline import process_fuchs_message

        result = await process_fuchs_message(msg_dict)

        # Проверяем, что logger.error был вызван с "DB Save Error"
        error_calls = [
            c for c in mock_logger.error.call_args_list
            if "DB Save Error" in str(c)
        ]
        assert len(error_calls) > 0, "DB Save Error should be logged"
