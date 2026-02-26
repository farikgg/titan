import logging
from typing import Dict, Any, Optional, List

from sqlalchemy.ext.asyncio import AsyncSession

from src.services.bitrix_service import BitrixService
from src.services.price_service import PriceService
from src.core.enums import Role
from src.app.config import BITRIX_STAGES

logger = logging.getLogger(__name__)


class DealService:
    """
    Управление жизненным циклом сделок в воронке «Гидротех».

    Полный цикл:
      create_deal  →  NEW
      confirm_deal →  PREPARATION
      attach_kp    →  KP_CREATED
      send_kp      →  KP_SENT
      win / lose   →  WON / LOSE
    """

    def __init__(
        self,
        bitrix_service: BitrixService,
        price_service: PriceService | None = None,
    ):
        self.bitrix = bitrix_service
        self.price_service = price_service or PriceService()

    # ──────────────────────────────────────────────
    #  CREATE  →  стадия NEW
    # ──────────────────────────────────────────────

    async def create_deal(
        self,
        title: str,
        assigned_by_id: int,
        *,
        currency: str = "KZT",
        company_id: int | None = None,
        contact_id: int | None = None,
        source_description: str | None = None,
        products: List[Dict] | None = None,
    ) -> Optional[int]:
        """
        Создаёт сделку в воронке Гидротех со стадией NEW.
        Если переданы products — привязывает их к сделке.
        Возвращает deal_id или None.
        """
        fields: Dict[str, Any] = {
            "TITLE": title,
            "ASSIGNED_BY_ID": assigned_by_id,
            "CURRENCY_ID": currency,
            "OPPORTUNITY": 0,
        }

        if company_id:
            fields["COMPANY_ID"] = company_id
        if contact_id:
            fields["CONTACT_ID"] = contact_id
        if source_description:
            fields["SOURCE_DESCRIPTION"] = source_description

        deal_id = await self.bitrix.create_deal(fields)
        if not deal_id:
            return None

        if products:
            await self.bitrix.set_deal_products(deal_id, products)

            # Пересчитываем сумму сделки по товарам
            total = sum(
                float(p.get("PRICE", 0)) * int(p.get("QUANTITY", 1))
                for p in products
            )
            if total > 0:
                await self.bitrix.update_deal(deal_id, {"OPPORTUNITY": total})

        logger.info("DealService: сделка создана id=%s, title=%s", deal_id, title)
        return deal_id

    # ──────────────────────────────────────────────
    #  Создание из распарсенного письма
    # ──────────────────────────────────────────────

    async def create_deal_from_email(
        self,
        subject: str,
        sender: str,
        assigned_by_id: int,
        parsed_items: List[Dict],
        message_id: str | None = None,
    ) -> Optional[int]:
        """
        Создаёт сделку из входящего письма.
        parsed_items — список товаров вида:
          [{"art": "...", "name": "...", "price": 100.0, "currency": "EUR", "quantity": 1}]
        """
        title = f"Заявка: {subject[:80]}" if subject else "Заявка из почты"

        # Формируем товарные строки для Bitrix24
        products = []
        for item in parsed_items:
            products.append({
                "PRODUCT_NAME": item.get("name", item.get("art", "—")),
                "PRICE": float(item.get("price", 0)),
                "QUANTITY": int(item.get("quantity", 1)),
            })

        source_desc = f"Email: {sender}"
        if message_id:
            source_desc += f" | Message-ID: {message_id}"

        return await self.create_deal(
            title=title,
            assigned_by_id=assigned_by_id,
            currency=parsed_items[0].get("currency", "KZT") if parsed_items else "KZT",
            source_description=source_desc,
            products=products if products else None,
        )

    # ──────────────────────────────────────────────
    #  TRANSITIONS  (смена стадий)
    # ──────────────────────────────────────────────

    async def move_to_preparation(self, deal_id: int) -> bool:
        """NEW → PREPARATION: менеджер подтвердил заявку и начал подготовку КП."""
        return await self.bitrix.update_deal_stage(deal_id, BITRIX_STAGES.PREPARATION)

    async def move_to_kp_created(self, deal_id: int) -> bool:
        """PREPARATION → KP_CREATED: PDF с КП сгенерирован."""
        return await self.bitrix.update_deal_stage(deal_id, BITRIX_STAGES.KP_CREATED)

    async def move_to_kp_sent(self, deal_id: int) -> bool:
        """KP_CREATED → KP_SENT: КП отправлено клиенту."""
        return await self.bitrix.update_deal_stage(deal_id, BITRIX_STAGES.KP_SENT)

    async def move_to_won(self, deal_id: int) -> bool:
        """KP_SENT → WON: сделка выиграна."""
        return await self.bitrix.update_deal_stage(deal_id, BITRIX_STAGES.WON)

    async def move_to_lost(self, deal_id: int) -> bool:
        """Любая стадия → LOSE: сделка проиграна."""
        return await self.bitrix.update_deal_stage(deal_id, BITRIX_STAGES.LOSE)

    # ──────────────────────────────────────────────
    #  READ
    # ──────────────────────────────────────────────

    async def get_deal_dto(
        self,
        deal_id: int,
        db: AsyncSession,
        supplier: str,
    ) -> Optional[Dict[str, Any]]:
        """Получает сделку с товарами и обогащёнными ценами."""
        deal = await self.bitrix.get_deal(deal_id)
        if not deal:
            return None

        products = await self.bitrix.get_deal_products(deal_id)

        skus = [p.get("PRODUCT_NAME", "") for p in products]
        resolved_prices = await self.price_service.resolve_prices(
            db=db,
            skus=skus,
            source=supplier,
        )

        return {
            "deal": {
                "id": int(deal["ID"]),
                "title": deal["TITLE"],
                "stage_id": deal["STAGE_ID"],
                "category_id": deal["CATEGORY_ID"],
                "currency": deal["CURRENCY_ID"],
                "opportunity": deal["OPPORTUNITY"],
                "assigned_by_id": deal["ASSIGNED_BY_ID"],
            },
            "products": products,
            "resolved_prices": resolved_prices,
        }

    async def list_deals_for_user(self, user) -> List[Dict]:
        """
        Row-level RBAC:
        - manager: только свои сделки (воронка Гидротех)
        - head-manager / admin: все сделки воронки
        """
        if user.role == Role.manager.value:
            return await self.bitrix.get_deals(
                bitrix_user_id=user.bitrix_user_id
            )
        return await self.bitrix.get_all_deals()
