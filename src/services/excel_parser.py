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
        try:
            df = pd.read_excel(BytesIO(content))
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Ошибка чтения Excel файла (возможно неверный формат): %s", e)
            return []
            
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


class FuchsAnalogExcelParser:
    """
    Парсит Excel файлы от Fuchs с аналогами.
    Формат A: col[1]=исходный товар, col[5]/col[7]=артикул+название аналога
    Формат B: col[0]=исходный товар, col[1]=артикул Fuchs (6-9 цифр), col[2]=название аналога
    Возвращает список dict: {source_name, source_code, analog_art, analog_name, analog_brand}
    """

    def parse(self, content: bytes) -> list[dict]:
        import logging
        _logger = logging.getLogger(__name__)
        results = []
        try:
            xl = pd.ExcelFile(BytesIO(content))
        except Exception as e:
            _logger.warning("Ошибка чтения Excel аналогов: %s", e)
            return []

        for sheet_name in xl.sheet_names:
            try:
                df = pd.read_excel(xl, sheet_name=sheet_name, header=None)
            except Exception:
                continue
            if df.empty or len(df.columns) < 2:
                continue
            parsed = self._try_format_b(df)
            if not parsed:
                parsed = self._try_format_a(df)
            results.extend(parsed)

        return results

    def _try_format_b(self, df: pd.DataFrame) -> list[dict]:
        """col[0]=исходный товар, col[1]=артикул Fuchs (6-9 цифр), col[2]=название"""
        col_b = df.iloc[:, 1]
        numeric_count = sum(1 for v in col_b.dropna() if re.match(r'^\d{6,9}$', str(v).strip()))
        if numeric_count < 2:
            return []

        items = []
        col_c = df.iloc[:, 2] if len(df.columns) > 2 else None
        for i, row in df.iterrows():
            source_name = str(row.iloc[0]).strip()
            analog_art = str(row.iloc[1]).strip()
            if not source_name or source_name.lower() in ("nan", "none", ""):
                continue
            if not re.match(r'^\d{6,9}$', analog_art):
                continue
            analog_name = str(col_c.iloc[i]).strip() if col_c is not None else ""
            if analog_name.lower() in ("nan", "none", ""):
                analog_name = None
            items.append({
                "source_name": source_name,
                "source_code": None,
                "analog_art": analog_art,
                "analog_name": analog_name,
                "analog_brand": "FUCHS",
            })
        return items

    def _try_format_a(self, df: pd.DataFrame) -> list[dict]:
        """col[1]=исходный товар, col[5] и col[7]=артикул+название аналога"""
        if len(df.columns) < 6:
            return []
        items = []
        for _, row in df.iterrows():
            source_name = str(row.iloc[1]).strip() if len(row) > 1 else ""
            if not source_name or source_name.lower() in ("nan", "none", ""):
                continue
            for col_idx in [5, 7]:
                if col_idx >= len(row):
                    continue
                cell = str(row.iloc[col_idx]).strip()
                if not cell or cell.lower() in ("nan", "none"):
                    continue
                art_match = re.search(r'\b(\d{6,9})\b', cell)
                if not art_match:
                    continue
                analog_art = art_match.group(1)
                analog_name = cell.replace(analog_art, "").strip() or None
                items.append({
                    "source_name": source_name,
                    "source_code": None,
                    "analog_art": analog_art,
                    "analog_name": analog_name,
                    "analog_brand": "FUCHS",
                })
        return items
