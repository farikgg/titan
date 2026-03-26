import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.price_model import PriceModel, Source
from src.db.models.product_analog_model import ProductAnalogModel

logger = logging.getLogger(__name__)


class FuchsPriceReportService:
    """
    Формирует Excel-отчёт по срокам действия цен FUCHS:
      - просроченные
      - скоро истекают (<=7 дней)
      - все позиции (с unit_price)
      - аналоги товаров
    """

    def __init__(self, expiring_days_threshold: int = 7):
        self.expiring_days_threshold = expiring_days_threshold

    async def build_report_xlsx(self, db: AsyncSession, *, output_dir: Path) -> Path:
        # Берём только FUCHS цены
        result = await db.execute(
            select(PriceModel).where(PriceModel.source == Source.FUCHS)
        )
        prices = list(result.scalars().all())

        # Собираем строки
        rows: list[dict] = []
        for p in prices:
            valid_to = p.valid_to
            status = p.validity_status

            rows.append(
                {
                    "art": p.art,
                    "name": p.name,
                    "price": float(p.price) if p.price is not None else None,
                    "currency": p.currency,
                    # Unit price fields
                    "container_size": float(p.container_size) if p.container_size is not None else None,
                    "container_unit": p.container_unit,
                    "unit_price": float(p.unit_price) if p.unit_price is not None else None,
                    "unit_measure": p.unit_measure,
                    "unit_price_missing": p.unit_price_missing,
                    # Validity fields
                    "first_seen_at": p.first_seen_at,
                    "valid_from": p.valid_from,
                    "valid_days": p.valid_days,
                    "days_left": p.days_left,
                    "valid_to": valid_to,
                    "status": status,
                    "email_message_id": p.email_message_id,
                    "updated_at": p.updated_at,
                }
            )

        df = pd.DataFrame(rows)

        if df.empty:
            # Если данных нет, создаем пустой DataFrame с нужными колонками,
            # чтобы избежать KeyError при фильтрации.
            df = pd.DataFrame(columns=[
                "art", "name", "price", "currency", "container_size",
                "container_unit", "unit_price", "unit_measure", "unit_price_missing",
                "first_seen_at", "valid_from", "valid_days", "days_left",
                "valid_to", "status", "email_message_id", "updated_at"
            ])

        # Фильтруем только проблемные цены
        df_expired = df[df["status"] == "expired"].copy()
        df_expiring = df[df["status"] == "expiring_soon"].copy()

        # Сортировки
        if not df_expired.empty:
            df_expired = df_expired.sort_values(by=["valid_to", "art"], ascending=[True, True])
        if not df_expiring.empty:
            df_expiring = df_expiring.sort_values(by=["valid_to", "art"], ascending=[True, True])

        # Аналоги
        analogs_result = await db.execute(select(ProductAnalogModel))
        analogs = list(analogs_result.scalars().all())

        analog_rows = [
            {
                "source_art": a.source_art,
                "analog_art": a.analog_art,
                "analog_name": a.analog_name,
                "analog_source": a.analog_source,
                "notes": a.notes,
                "created_at": a.created_at,
            }
            for a in analogs
        ]
        df_analogs = pd.DataFrame(analog_rows if analog_rows else [])

        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.utcnow().strftime("%Y-%m-%d")
        out_path = output_dir / f"fuchs_price_expiry_report_{stamp}.xlsx"

        with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
            df_expired.to_excel(writer, index=False, sheet_name="expired")
            df_expiring.to_excel(writer, index=False, sheet_name="expiring_soon")
            # Полная выгрузка
            df.to_excel(writer, index=False, sheet_name="all")
            # Аналоги
            if not df_analogs.empty:
                df_analogs.to_excel(writer, index=False, sheet_name="analogs")

        logger.info(
            "FUCHS price report generated: %s (expired=%d, expiring=%d, total=%d, analogs=%d)",
            out_path,
            len(df_expired),
            len(df_expiring),
            len(df),
            len(analog_rows),
        )
        return out_path

