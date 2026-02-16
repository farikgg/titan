import pandas as pd
from io import BytesIO
from decimal import Decimal

from src.schemas.price_schema import PriceCreate
from src.db.models.price_model import Source, SourceType


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

            items.append(
                PriceCreate(
                    art=art,
                    name=name,
                    price=price,
                    currency="EUR",
                    source=Source.FUCHS,
                    source_type=SourceType.EMAIL,
                )
            )

        return items

