import logging
from typing import List, Dict, Optional

from anyio import to_thread
from fast_bitrix24 import Bitrix

logger = logging.getLogger(__name__)


class BitrixService:
    def __init__(self, bx: Bitrix):
        self.bx = bx

    async def get_deals(self, bitrix_user_id: int) -> List[Dict]:
        try:
            result = await to_thread.run_sync(
                self.bx.call,
                "crm.deal.list",
                {
                    "filter": {
                        "ASSIGNED_BY_ID": bitrix_user_id,
                        "CLOSED": "N",
                    },
                    "select": [
                        "ID",
                        "TITLE",
                        "STAGE_ID",
                        "CATEGORY_ID",
                        "OPPORTUNITY",
                        "CURRENCY_ID",
                        "ASSIGNED_BY_ID",
                    ],
                },
            )
            return result or []
        except Exception:
            logger.exception("Bitrix: ошибка получения списка сделок")
            return []

    async def get_deal(self, deal_id: int) -> Optional[Dict]:
        try:
            return await to_thread.run_sync(
                self.bx.call,
                "crm.deal.get",
                {"id": deal_id},
            )
        except Exception:
            logger.exception("Bitrix: ошибка получения сделки %s", deal_id)
            return None

    async def get_deal_products(self, deal_id: int) -> List[Dict]:
        try:
            result = await to_thread.run_sync(
                self.bx.call,
                "crm.deal.productrows.get",
                {"id": deal_id},
            )
            return result or []
        except Exception:
            logger.exception(
                "Bitrix: ошибка получения товаров сделки %s", deal_id
            )
            return []

    async def create_deal(self, title: str, amount: float) -> Optional[int]:
        try:
            result = await to_thread.run_sync(
                self.bx.call,
                "crm.deal.add",
                {
                    "fields": {
                        "TITLE": title,
                        "OPPORTUNITY": amount,
                        "CURRENCY_ID": "KZT",
                    }
                },
            )
            return int(result)
        except Exception:
            logger.exception("Bitrix: ошибка создания сделки")
            return None

    async def set_deal_products(
        self, deal_id: int, products: List[Dict]
    ) -> bool:
        try:
            await to_thread.run_sync(
                self.bx.call,
                "crm.deal.productrows.set",
                {
                    "id": deal_id,
                    "rows": products,
                },
            )
            return True
        except Exception:
            logger.exception(
                "Bitrix: ошибка установки товаров для сделки %s", deal_id
            )
            return False

    async def get_all_deals(self):
        try:
            result = await to_thread.run_sync(
                self.bx.call,
                "crm.deal.list",
                {
                    "filter": {"CLOSED": "N"},
                    "select": [
                        "ID",
                        "TITLE",
                        "STAGE_ID",
                        "CATEGORY_ID",
                        "OPPORTUNITY",
                        "CURRENCY_ID",
                        "ASSIGNED_BY_ID",
                    ],
                },
            )
            return result or []
        except Exception:
            logger.exception("Bitrix: error fetching all deals")
            return []
