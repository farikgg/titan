from datetime import datetime

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Text, UniqueConstraint, func, DateTime

from src.db.initialize import Base


class ProductAnalogModel(Base):
    """
    Хранение аналогов товаров.
    Один товар (source_art) может иметь множество аналогов.
    Накапливается как база знаний, чтобы не отправлять повторные запросы поставщику.
    """
    __tablename__ = "product_analogs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # Артикул основного товара
    source_art: Mapped[str] = mapped_column(String(100), index=True)
    # Артикул аналога
    analog_art: Mapped[str] = mapped_column(String(100), index=True)
    # Название аналога (для удобства, чтобы не делать лишний join)
    analog_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Поставщик аналога: fuchs / skf / other
    analog_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Комментарий менеджера
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("source_art", "analog_art", name="uq_analog_pair"),
    )
