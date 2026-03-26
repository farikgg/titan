import re

import pandas as pd
from io import BytesIO
from decimal import Decimal

from src.schemas.price_schema import PriceCreate
from src.db.models.price_model import Source, SourceType


# Паттерны для поиска колонки с объёмом/весом тары
_CONTAINER_COL_PATTERNS = (
    "pack size", "container", "volume", "net weight",
    "package", "filling", "gebinde", "inhalt",
    "drum", "pail", "can", "barrel",
    "упаковка", "тара", "вес", "объем", "фасовка", "размер"
)

# Regex для извлечения числа + единицы из строки вида "200 L", "20kg", "180 KG drum", "20 л", "180 кг"
_SIZE_UNIT_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(l|L|liter|litre|kg|KG|kilogram|л|кг|литр|литров)\b",
    re.IGNORECASE,
)


def _parse_container_value(raw) -> tuple[Decimal | None, str | None]:
    """
    Парсит значение ячейки с объёмом тары.
    Примеры: "200 L", "20kg", 180, "5 Liter Kanister"
    Возвращает (container_size, container_unit) или (None, None)
    """
    if pd.isna(raw):
        return None, None

    text = str(raw).strip()
    if not text:
        return None, None

    # Попытка regex
    m = _SIZE_UNIT_RE.search(text)
    if m:
        size = Decimal(m.group(1).replace(",", "."))
        unit_raw = m.group(2).upper().strip()
        unit = "KG" if unit_raw.startswith("K") or unit_raw.startswith("КГ") else "L"
        return size, unit

    # Если только число без единицы — берём число, единица null
    try:
        size = Decimal(str(raw).replace(",", ".").strip())
        if size > 0:
            return size, None
    except Exception:
        pass

    return None, None


class FuchsExcelParser:
    def parse(self, content: bytes) -> list[PriceCreate]:
        df = pd.read_excel(BytesIO(content))
        df = df.rename(str.lower, axis=1)

        # ищем колонку с ценой
        price_col = None
        for col in df.columns:
            if "price" in col and "€" in col:
                price_col = col
                break

        if not price_col:
            return []

        # ищем колонку с объёмом/весом тары
        container_col = None
        for col in df.columns:
            col_lower = col.lower()
            if any(p in col_lower for p in _CONTAINER_COL_PATTERNS):
                container_col = col
                break

        items: list[PriceCreate] = []
        seen: set[tuple[str, Decimal | None]] = set()

        for _, row in df.iterrows():
            sap = str(row.get("sap number", "")).strip()
            fuchs_alt = str(row.get("fuchs alternative", "")).strip()
            product_name = str(row.get(df.columns[0], "")).strip()

            # art
            art = sap or fuchs_alt
            if not art:
                continue

            # name
            name = fuchs_alt or product_name
            if not name or name.lower() == "nan":
                continue

            price_raw = row.get(price_col)
            price = None
            if pd.notna(price_raw):
                price = Decimal(str(price_raw).replace(",", "."))

            key = (art, price)
            if key in seen:
                continue
            seen.add(key)

            # Container info
            container_size = None
            container_unit = None
            if container_col is not None:
                container_size, container_unit = _parse_container_value(row.get(container_col))

            # Также пытаемся извлечь из названия, если в колонке не нашли
            if container_size is None:
                container_size, container_unit = _parse_container_value(name)

            items.append(
                PriceCreate(
                    art=art,
                    name=name,
                    raw_name=product_name, # используем оригинальное имя из первой колонки
                    price=price,
                    unit=None, # в старых Excel нет колонки с unit
                    currency="EUR",
                    source=Source.FUCHS,
                    source_type=SourceType.EMAIL,
                    container_size=container_size,
                    container_unit=container_unit,
                )
            )

        return items


