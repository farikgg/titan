"""
Тесты для PriceService.calculate_unit_price и _enrich_unit_price
"""
import pytest
from decimal import Decimal

from src.services.price_service import PriceService
from src.schemas.price_schema import PriceCreate
from src.db.models.price_model import Source, SourceType


class TestCalculateUnitPrice:
    """Unit тесты для PriceService.calculate_unit_price"""

    def test_basic_liter(self):
        """501 EUR / 200 L → 2.505 per_liter"""
        unit_price, unit_measure = PriceService.calculate_unit_price(
            price=Decimal("501"), container_size=Decimal("200"), container_unit="L"
        )
        assert unit_price == Decimal("2.5050")
        assert unit_measure == "per_liter"

    def test_basic_kg(self):
        """100 EUR / 20 KG → 5.0 per_kg"""
        unit_price, unit_measure = PriceService.calculate_unit_price(
            price=Decimal("100"), container_size=Decimal("20"), container_unit="KG"
        )
        assert unit_price == Decimal("5.0000")
        assert unit_measure == "per_kg"

    def test_no_container_size(self):
        """Без данных о таре → None"""
        unit_price, unit_measure = PriceService.calculate_unit_price(
            price=Decimal("100"), container_size=None, container_unit="L"
        )
        assert unit_price is None
        assert unit_measure is None

    def test_no_price(self):
        """Без цены → None"""
        unit_price, unit_measure = PriceService.calculate_unit_price(
            price=None, container_size=Decimal("200"), container_unit="L"
        )
        assert unit_price is None
        assert unit_measure is None

    def test_zero_container_size(self):
        """Нулевой размер тары → None (деление на 0)"""
        unit_price, unit_measure = PriceService.calculate_unit_price(
            price=Decimal("100"), container_size=Decimal("0"), container_unit="L"
        )
        assert unit_price is None
        assert unit_measure is None

    def test_zero_price(self):
        """Нулевая цена → None"""
        unit_price, unit_measure = PriceService.calculate_unit_price(
            price=Decimal("0"), container_size=Decimal("200"), container_unit="L"
        )
        assert unit_price is None
        assert unit_measure is None

    def test_float_inputs(self):
        """Принимает float"""
        unit_price, unit_measure = PriceService.calculate_unit_price(
            price=501.0, container_size=200.0, container_unit="L"
        )
        assert unit_price == Decimal("2.5050")
        assert unit_measure == "per_liter"

    def test_unknown_unit(self):
        """Неизвестная единица → per_unit"""
        unit_price, unit_measure = PriceService.calculate_unit_price(
            price=Decimal("100"), container_size=Decimal("20"), container_unit="gal"
        )
        assert unit_price is not None
        assert unit_measure == "per_unit"

    def test_case_insensitive_unit(self):
        """Единицы нечувствительны к регистру"""
        _, m1 = PriceService.calculate_unit_price(100, 20, "l")
        _, m2 = PriceService.calculate_unit_price(100, 20, "L")
        _, m3 = PriceService.calculate_unit_price(100, 20, "kg")
        _, m4 = PriceService.calculate_unit_price(100, 20, "KG")
        assert m1 == m2 == "per_liter"
        assert m3 == m4 == "per_kg"

    def test_unit_with_spaces(self):
        """Единицы с пробелами"""
        _, m = PriceService.calculate_unit_price(100, 20, " L ")
        assert m == "per_liter"

    def test_precision(self):
        """Точность 4 десятичных знака"""
        unit_price, _ = PriceService.calculate_unit_price(
            price=Decimal("1000"), container_size=Decimal("3"), container_unit="L"
        )
        # 1000 / 3 = 333.3333...
        assert unit_price == Decimal("333.3333")


class TestEnrichUnitPrice:
    """Тесты для _enrich_unit_price"""

    def _make_price_create(self, **kwargs) -> PriceCreate:
        defaults = {
            "art": "TEST-001",
            "name": "Test Product",
            "price": Decimal("500"),
            "currency": "EUR",
            "source": Source.FUCHS,
            "source_type": SourceType.EMAIL,
        }
        defaults.update(kwargs)
        return PriceCreate(**defaults)

    def test_enrich_with_container_data(self):
        """Если есть container, считает unit_price"""
        pc = self._make_price_create(
            container_size=Decimal("200"),
            container_unit="L",
        )
        result = PriceService._enrich_unit_price(pc)
        assert result.unit_price == Decimal("2.5000")
        assert result.unit_measure == "per_liter"
        assert result.unit_price_missing is False

    def test_enrich_without_container(self):
        """Если нет container, ставит unit_price_missing=True"""
        pc = self._make_price_create()
        result = PriceService._enrich_unit_price(pc)
        assert result.unit_price_missing is True

    def test_enrich_no_price(self):
        """Если нет ни цены, ни контейнера — ничего не меняется"""
        pc = self._make_price_create(price=None)
        result = PriceService._enrich_unit_price(pc)
        # Нет цены — нет флага missing (нечего считать)
        assert getattr(result, "unit_price_missing", None) in (None, False)


class TestExcelParserContainerExtraction:
    """Тесты для _parse_container_value"""

    def test_parse_200_l(self):
        from src.services.excel_parser import _parse_container_value
        size, unit = _parse_container_value("200 L drum")
        assert size == Decimal("200")
        assert unit == "L"

    def test_parse_20_kg(self):
        from src.services.excel_parser import _parse_container_value
        size, unit = _parse_container_value("20kg pail")
        assert size == Decimal("20")
        assert unit == "KG"

    def test_parse_number_only(self):
        from src.services.excel_parser import _parse_container_value
        size, unit = _parse_container_value("180")
        assert size == Decimal("180")
        assert unit is None

    def test_parse_5_liter(self):
        from src.services.excel_parser import _parse_container_value
        size, unit = _parse_container_value("5 Liter Kanister")
        assert size == Decimal("5")
        assert unit == "L"

    def test_parse_nan(self):
        import pandas as pd
        from src.services.excel_parser import _parse_container_value
        size, unit = _parse_container_value(pd.NA)
        assert size is None
        assert unit is None

    def test_parse_empty(self):
        from src.services.excel_parser import _parse_container_value
        size, unit = _parse_container_value("")
        assert size is None
        assert unit is None
