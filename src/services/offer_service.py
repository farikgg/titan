from decimal import Decimal
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.offer_model import OfferModel, OfferStatus
from src.db.models.offer_item_model import OfferItemModel
from src.db.models.audit_log import AuditLog
from src.db.models.price_model import PriceModel


class OfferService:

    def __init__(self, db: AsyncSession):
        self.db = db

    # --------------------------------------------------
    # Draft
    # --------------------------------------------------

    async def get_or_create_draft(self, user_id: int) -> OfferModel:
        result = await self.db.execute(
            select(OfferModel).where(
                OfferModel.user_id == user_id,
                OfferModel.status == OfferStatus.DRAFT,
            )
        )
        offer = result.scalar_one_or_none()

        if offer:
            return offer

        offer = OfferModel(
            user_id=user_id,
            status=OfferStatus.DRAFT,
            total=Decimal("0.00"),
            currency=None,
        )
        self.db.add(offer)
        await self.db.commit()
        await self.db.refresh(offer)

        return offer

    async def create_draft(self, user_id: int) -> OfferModel:
        """
        Обёртка для совместимости с роутером `/offers/draft`.
        Фактически делает то же самое, что и `get_or_create_draft`.
        """
        return await self.get_or_create_draft(user_id)

    # --------------------------------------------------
    # Add item
    # --------------------------------------------------

    async def add_item(self, offer_id: int, sku: str, quantity: int = 1):

        offer = await self.db.get(OfferModel, offer_id)
        if not offer:
            raise ValueError("Offer not found")

        price_obj = await self.db.scalar(
            select(PriceModel).where(PriceModel.art == sku)
        )

        if not price_obj:
            raise ValueError("SKU not found")

        # ---------------- ВАЛЮТА ----------------

        if not offer.currency:
            offer.currency = price_obj.currency

        if offer.currency != price_obj.currency:
            raise ValueError("Mixed currencies are not allowed")

        # ---------------- ПРОВЕРКА СУЩЕСТВУЕТ ЛИ ТОВАР ----------------

        existing = await self.db.scalar(
            select(OfferItemModel).where(
                OfferItemModel.offer_id == offer_id,
                OfferItemModel.sku == sku,
            )
        )

        if existing:
            existing.quantity += quantity
            existing.total = existing.quantity * existing.price
        else:
            item = OfferItemModel(
                offer_id=offer_id,
                sku=sku,
                name=price_obj.name,
                price=price_obj.price,
                quantity=quantity,
                total=price_obj.price * quantity,
            )
            self.db.add(item)

        # ---------------- ПЕРЕСЧЁТ ИТОГА ----------------

        await self.recalc_total(offer_id)

        await self._log(
            actor_type="user",
            action="add_item",
            payload={"offer_id": offer_id, "sku": sku},
        )

        await self.db.commit()

    # --------------------------------------------------
    # Remove item
    # --------------------------------------------------

    async def remove_item(self, offer_id: int, sku: str):
        """Удаляет товар из коммерческого предложения"""
        offer = await self.db.get(OfferModel, offer_id)
        if not offer:
            raise ValueError("Offer not found")

        # Проверяем, существует ли товар
        item = await self.db.scalar(
            select(OfferItemModel).where(
                OfferItemModel.offer_id == offer_id,
                OfferItemModel.sku == sku,
            )
        )

        if not item:
            raise ValueError("Item not found in offer")

        # Удаляем товар через delete statement
        await self.db.execute(
            delete(OfferItemModel).where(
                OfferItemModel.offer_id == offer_id,
                OfferItemModel.sku == sku,
            )
        )

        # Пересчитываем итог
        await self.recalc_total(offer_id)

        await self._log(
            actor_type="user",
            action="remove_item",
            payload={"offer_id": offer_id, "sku": sku},
        )

        await self.db.commit()

    # --------------------------------------------------
    # Clear
    # --------------------------------------------------

    async def clear_offer(self, offer_id: int):
        await self.db.execute(
            delete(OfferItemModel).where(
                OfferItemModel.offer_id == offer_id
            )
        )

        offer = await self.db.get(OfferModel, offer_id)
        offer.total = Decimal("0.00")

        await self._log(
            actor_type="user",
            action="clear_offer",
            payload={"offer_id": offer_id},
        )

    # --------------------------------------------------
    # Recalc
    # --------------------------------------------------

    async def recalc_total(self, offer_id: int):
        result = await self.db.execute(
            select(OfferItemModel).where(
                OfferItemModel.offer_id == offer_id
            )
        )
        items = result.scalars().all()

        total = sum(i.total for i in items) if items else Decimal("0.00")

        offer = await self.db.get(OfferModel, offer_id)
        offer.total = total

    # --------------------------------------------------
    # PDF Status
    # --------------------------------------------------

    async def mark_generated(self, offer_id: int):

        offer = await self.db.get(OfferModel, offer_id)

        if offer.status != OfferStatus.DRAFT:
            raise ValueError("PDF already generated")

        offer.status = OfferStatus.GENERATED

        await self._log(
            actor_type="system",
            action="generate_pdf",
            payload={"offer_id": offer_id},
        )

    # --------------------------------------------------
    # Convert
    # --------------------------------------------------

    async def convert_to_bitrix(self, offer_id: int, assigned_by_id: int = 1):
        """
        Конвертирует КП в сделку в воронке Гидротех.
        1. Создаёт сделку (стадия NEW)
        2. Привязывает товары
        3. Переводит в PREPARATION
        """
        offer = await self.db.get(OfferModel, offer_id)

        if not offer:
            raise ValueError("Offer not found")

        if offer.status == OfferStatus.CONVERTED:
            raise ValueError("Already converted")

        from src.core.bitrix import get_bitrix_client
        from src.services.bitrix_service import BitrixService
        from src.services.deal_service import DealService

        bx = get_bitrix_client()
        bitrix = BitrixService(bx)
        deal_service = DealService(bitrix)

        # Получаем товары КП
        result = await self.db.execute(
            select(OfferItemModel).where(
                OfferItemModel.offer_id == offer_id
            )
        )
        items = result.scalars().all()

        products = [
            {
                "PRODUCT_NAME": item.name,
                "PRICE": float(item.price),
                "QUANTITY": item.quantity,
            }
            for item in items
        ]

        # Создаём сделку в Bitrix24 (стадия NEW → сразу PREPARATION)
        deal_id = await deal_service.create_deal(
            title=f"КП #{offer.id}",
            assigned_by_id=assigned_by_id,
            currency=offer.currency or "KZT",
            products=products,
        )

        if not deal_id:
            raise ValueError("Failed to create deal in Bitrix24")

        # Переводим в стадию PREPARATION
        await deal_service.move_to_preparation(deal_id)

        offer.bitrix_deal_id = str(deal_id)
        offer.status = OfferStatus.CONVERTED

        await self._log(
            actor_type="system",
            action="convert_to_bitrix",
            payload={"offer_id": offer_id, "deal_id": deal_id},
        )

        return deal_id

    # --------------------------------------------------
    # History
    # --------------------------------------------------

    async def get_user_offers(self, user_id: int):

        result = await self.db.execute(
            select(OfferModel).where(
                OfferModel.user_id == user_id
            )
        )

        offers = result.scalars().all()

        return [
            {
                "id": o.id,
                "status": o.status.value,
                "total": float(o.total),
                "bitrix_deal_id": o.bitrix_deal_id,
            }
            for o in offers
        ]

    # --------------------------------------------------
    # Audit
    # --------------------------------------------------

    async def _log(self, actor_type: str, action: str, payload: dict):

        log = AuditLog(
            actor_type=actor_type,
            actor_id=None,
            action=action,
            payload=payload,
        )
        self.db.add(log)

    # --------------------------------------------------
    # Get offer with items
    # --------------------------------------------------

    async def get_offer_with_items(self, offer_id: int):

        offer = await self.db.get(OfferModel, offer_id)

        result = await self.db.execute(
            select(OfferItemModel).where(
                OfferItemModel.offer_id == offer_id
            )
        )
        items = result.scalars().all()

        return {
            "id": offer.id,
            "status": offer.status.value,
            "total": float(offer.total),
            "bitrix_deal_id": offer.bitrix_deal_id,
            "items": [
                {
                    "sku": i.sku,
                    "name": i.name,
                    "price": float(i.price),
                    "quantity": i.quantity,
                    "total": float(i.total),
                }
                for i in items
            ],
        }
