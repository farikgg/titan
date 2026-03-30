from datetime import datetime

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Text, Float, UniqueConstraint, func, DateTime

from src.db.initialize import Base


class ProductAnalogModel(Base):
    """
    База знаний аналогов товаров.
    Один товар (source) может иметь множество аналогов.
    """
    __tablename__ = "product_analogs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # --- Исходный товар ---
    source_product_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_product_code: Mapped[str] = mapped_column(String(100), index=True)
    source_brand: Mapped[str | None] = mapped_column(String(200), nullable=True)
    supplier_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # --- Аналог ---
    analog_product_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    analog_product_code: Mapped[str] = mapped_column(String(100), index=True)
    analog_brand: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # --- Метаданные ---
    match_type: Mapped[str | None] = mapped_column(
        String(10), nullable=True, comment="1:1 or 1:N"
    )
    confidence_level: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="0.0 to 1.0"
    )
    status: Mapped[str] = mapped_column(
        String(20), default="new", server_default="new", index=True,
        comment="new / confirmed / archived",
    )
    added_from: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="email / manual / import"
    )
    email_thread_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    confirmed_by: Mapped[int | None] = mapped_column(nullable=True, comment="user.id менеджера")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # --- Обратная совместимость (алиасы на старые имена) ---
    @property
    def source_art(self) -> str:
        return self.source_product_code

    @property
    def analog_art(self) -> str:
        return self.analog_product_code

    @property
    def analog_name(self) -> str | None:
        return self.analog_product_name

    @property
    def analog_source(self) -> str | None:
        return self.supplier_name

    __table_args__ = (
        UniqueConstraint(
            "source_product_code", "analog_product_code",
            name="uq_analog_pair",
        ),
    )
