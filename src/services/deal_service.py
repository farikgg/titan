import logging
from typing import Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.services.bitrix_service import BitrixService
from src.services.price_service import PriceService
from src.core.enums import Role

logger = logging.getLogger(__name__)


class DealService:
    def __init__(
        self,
        bitrix_service: BitrixService,
        price_service: PriceService,
    ):
        self.bitrix_service = bitrix_service
        self.price_service = price_service

    async def get_deal_dto(
        self,
        deal_id: int,
        db: AsyncSession,
        supplier: str,
    ) -> Optional[Dict[str, Any]]:
        deal = await self.bitrix_service.get_deal(deal_id)
        if not deal:
            return None

        products = await self.bitrix_service.get_deal_products(deal_id)

        resolved_prices = await self.price_service.resolve_prices(
            db=db,
            items=products,
            supplier=supplier,
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
            "items": resolved_prices,
        }

    async def create_deal_from_payload(
        self,
        payload: Dict[str, Any],
    ) -> Optional[int]:
        fields = {
            "TITLE": payload["title"],
            "CATEGORY_ID": payload["category_id"],
            "STAGE_ID": payload["stage_id"],
            "ASSIGNED_BY_ID": payload["assigned_by_id"],
            "CURRENCY_ID": payload.get("currency", "KZT"),
            "OPPORTUNITY": 0,
            "COMPANY_ID": payload.get("company_id"),
            "CONTACT_ID": payload.get("contact_id"),
        }

        deal_id = await self.bitrix_service.create_deal(fields)
        if not deal_id:
            return None

        if payload.get("products"):
            await self.bitrix_service.set_deal_products(
                deal_id=deal_id,
                products=payload["products"],
            )

        return deal_id

    async def list_deals_for_user(self, user):
        """
        Row-level RBAC:
        - manager: только свои сделки
        - head-manager/admin: все сделки
        """
        if user.role == Role.manager.value:
            return await self.bitrix_service.get_deals(
                bitrix_user_id=user.bitrix_user_id
            )
        # для head-manager и admin
        return await self.bitrix_service.get_all_deals()
