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

    # Проверяем, что в базе создалась запись об аналоге со статусом new и added_from=ai
    stmt = select(ProductAnalogModel).where(ProductAnalogModel.source_product_code == "UNKNOWN-SRC-CODE")
    result = await db.execute(stmt)
    analog_link = result.scalar_one_or_none()
    
    assert analog_link is not None
    assert analog_link.analog_product_code == "AI-ANALOG-001"
    assert analog_link.status == "new"
    assert analog_link.added_from == "ai"
    assert analog_link.confidence_level == 0.95
