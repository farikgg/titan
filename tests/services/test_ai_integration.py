import pytest
from unittest.mock import AsyncMock, patch
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.services.offer_service import OfferService
from src.db.models.price_model import PriceModel, Source, SourceType
from src.db.models.product_analog_model import ProductAnalogModel
from src.db.models.offer_model import OfferModel
from src.db.models.offer_item_model import OfferItemModel

@pytest.mark.asyncio
async def test_create_offer_with_ai_substitution(db: AsyncSession):
    """
    E2E тест: письмо с товаром которого нет в базе → проверить AI-подстановку.
    """
    # 1. Подготовка данных: товар-кандидат есть в базе
    candidate = PriceModel(
        art="AI-ANALOG-001",
        name="AI Found Analog",
        source=Source.FUCHS,
        price=Decimal("1500.00"),
        currency="KZT",
        source_type=SourceType.API,
        container_unit="л"
    )
    db.add(candidate)
    await db.commit()

    # 2. Мокаем вызов AI
    mock_ai_result = {
        "status": "auto",
        "analog_product_code": "AI-ANALOG-001",
        "analog_product_name": "AI Found Analog",
        "analog_brand": "FUCHS",
        "score": 0.95,
        "reason": "AI matched it perfectly",
        "match_type": "exact_code"
    }

    # Ингредиенты для оффера
    items = [
        {
            "sku": "UNKNOWN-SRC-CODE",
            "name": "Unknown Source Product",
            "quantity": 2,
            "found": False
        }
    ]

    service = OfferService(db)

    # Патчим AnalogAISearch.search
    # В offer_service.py импорт происходит внутри метода
    with patch("src.services.analog_ai_search.AnalogAISearch.search", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_ai_result
        
        # 3. Вызываем основной метод пайплайна
        offer = await service.create_offer_for_deal(
            deal_id=123,
            bitrix_user_id=1,
            items=items
        )

    # 4. Проверки
    # Проверяем, что товар заменился на аналог
    stmt_items = select(OfferItemModel).where(OfferItemModel.offer_id == offer.id)
    res_items = await db.execute(stmt_items)
    offer_items = res_items.scalars().all()
    
    assert len(offer_items) == 1
    item = offer_items[0]
    assert item.sku == "AI-ANALOG-001"
    assert "[АНАЛОГ ИИ]" in item.name
    assert item.price == Decimal("1500.00")
    assert item.total == Decimal("3000.00")
    assert item.added_from == "ai"
    assert item.reason == "AI matched it perfectly"
    assert item.confidence_level == 0.95
    assert item.analog_id is not None

    # Проверяем ответ API (get_offer_with_items)
    offer_data = await service.get_offer_with_items(offer.id)
    api_item = offer_data["items"][0]
    assert api_item["added_from"] == "ai"
    assert api_item["reason"] == "AI matched it perfectly"
    assert api_item["confidence_level"] == 0.95
    assert api_item["analog_id"] == item.analog_id
    assert api_item["analog_status"] == "new"

    # 5. Проверяем обновление статуса после подтверждения
    stmt_analog = select(ProductAnalogModel).where(ProductAnalogModel.id == item.analog_id)
    analog_res = await db.execute(stmt_analog)
    analog_obj = analog_res.scalar_one()
    analog_obj.status = "confirmed"
    await db.commit()

    # Снова проверяем через API
    offer_data_2 = await service.get_offer_with_items(offer.id)
    assert offer_data_2["items"][0]["analog_status"] == "confirmed"

    # Проверяем, что в базе есть запись об аналоге (старая проверка)
    assert analog_obj.source_product_code == "UNKNOWN-SRC-CODE"
    assert analog_obj.added_from == "ai"
