from decimal import Decimal
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.offer_model import OfferModel, OfferStatus
from src.db.models.offer_item_model import OfferItemModel
from src.db.models.audit_log import AuditLog
from src.db.models.price import PriceModel


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
        )
        self.db.add(offer)
        await self.db.flush()
        return offer

    # --------------------------------------------------
    # Add item
    # --------------------------------------------------

    async def add_item(self, offer_id: int, sku: str, quantity: int = 1):

        result = await self.db.execute(
            select(PriceModel).where(PriceModel.art == sku)
        )
        price_obj = result.scalar_one_or_none()

        if not price_obj:
            raise ValueError("SKU not found")

        result = await self.db.execute(
            select(OfferItemModel).where(
                OfferItemModel.offer_id == offer_id,
                OfferItemModel.sku == sku,
            )
        )
        existing = result.scalar_one_or_none()

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

        await self.recalc_total(offer_id)

        await self._log(
            actor_type="user",
            action="add_item",
            payload={"offer_id": offer_id, "sku": sku},
        )

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

    async def convert_to_bitrix(self, offer_id: int):

        offer = await self.db.get(OfferModel, offer_id)

        if offer.status == OfferStatus.CONVERTED:
            raise ValueError("Already converted")

        from src.core.bitrix import get_bitrix_client
        from src.services.bitrix_service import BitrixService

        bx = get_bitrix_client()
        bitrix = BitrixService(bx)

        deal = await bitrix.create_deal(
            title=f"КП #{offer.id}",
            amount=float(offer.total),
        )

        offer.bitrix_deal_id = deal["ID"]
        offer.status = OfferStatus.CONVERTED

        await self._log(
            actor_type="system",
            action="convert_to_bitrix",
            payload={"offer_id": offer_id, "deal_id": deal["ID"]},
        )

        return deal["ID"]

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
