from datetime import datetime

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, JSON, DateTime, func

from src.db.initialize import Base


class AnalogRequestModel(Base):
    """
    Запросы на подбор аналогов.
    Создаётся, когда pipeline не может автоматически подобрать аналог
    и заявка ожидает действий менеджера в Mini App.
    """
    __tablename__ = "analog_requests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # --- Контекст сделки ---
    deal_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    client_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # --- Товар, для которого ищем аналог ---
    product_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    product_code: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    brand: Mapped[str | None] = mapped_column(String(200), nullable=True)
    supplier: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # --- Статус обработки ---
    request_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", index=True,
        comment="pending / sent / answered / resolved",
    )

    # --- Временные метки ---
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    response_received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # --- Результат парсинга ответа ---
    parsed_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # --- Менеджер, ответственный за запрос ---
    manager_id: Mapped[int | None] = mapped_column(nullable=True, comment="user.id менеджера")

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
