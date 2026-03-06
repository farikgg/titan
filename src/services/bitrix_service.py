import logging
from typing import List, Dict, Optional

from anyio import to_thread
from fast_bitrix24 import Bitrix

from src.app.config import BITRIX_STAGES

logger = logging.getLogger(__name__)


class BitrixService:
    def __init__(self, bx: Bitrix):
        self.bx = bx

    async def get_deals(self, bitrix_user_id: int, stage_id: str | None = None) -> List[Dict]:
        try:
            # Сначала пробуем найти сделки в воронке Гидротех (CATEGORY_ID = 9)
            # Используем get_all() для методов .list, как рекомендует fast_bitrix24
            filter_dict = {
                "ASSIGNED_BY_ID": bitrix_user_id,
                "CATEGORY_ID": BITRIX_STAGES.CATEGORY_ID,
                "CLOSED": "N",
            }
            # Если указана стадия — добавляем фильтр
            if stage_id:
                filter_dict["STAGE_ID"] = stage_id
            
            result = await to_thread.run_sync(
                self.bx.get_all,
                "crm.deal.list",
                {
                    "filter": filter_dict,
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
            # get_all() всегда возвращает список
            deals = list(result) if result else []
            logger.info(
                "Bitrix: найдено %d сделок для пользователя %s в воронке %s",
                len(deals),
                bitrix_user_id,
                BITRIX_STAGES.CATEGORY_ID,
            )
            
            # Если в воронке Гидротех ничего нет — пробуем все незакрытые сделки пользователя
            if not deals:
                logger.info(
                    "Bitrix: сделок в воронке %s не найдено, ищу все незакрытые сделки пользователя %s",
                    BITRIX_STAGES.CATEGORY_ID,
                    bitrix_user_id,
                )
                result = await to_thread.run_sync(
                    self.bx.get_all,
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
                # get_all() всегда возвращает список
                deals = list(result) if result else []
                logger.info(
                    "Bitrix: найдено %d незакрытых сделок пользователя %s (все воронки)",
                    len(deals),
                    bitrix_user_id,
                )
            
            return deals
        except Exception:
            logger.exception("Bitrix: ошибка получения списка сделок")
            return []

    async def get_deal(self, deal_id: int) -> Optional[Dict]:
        try:
            result = await to_thread.run_sync(
                self.bx.call,
                "crm.deal.get",
                {"id": deal_id},
            )
            
            # fast_bitrix24 может вернуть словарь с ключом "result" или список
            if isinstance(result, dict):
                # Если есть ключ "result" — извлекаем данные оттуда
                if "result" in result:
                    inner_result = result["result"]
                    # Если внутри словарь — это и есть сделка
                    if isinstance(inner_result, dict):
                        result = inner_result
                    # Если внутри список — берём первый элемент
                    elif isinstance(inner_result, list):
                        result = inner_result[0] if inner_result else None
                    else:
                        result = inner_result
                # Если нет ключа "result", но есть "ID" — это уже сделка
                elif "ID" in result:
                    pass  # result уже правильный
                else:
                    logger.warning(
                        "Bitrix: get_deal вернул словарь без 'ID' и без 'result'. "
                        "Тип: %s, ключи: %s, значение: %s",
                        type(result),
                        list(result.keys()) if isinstance(result, dict) else None,
                        result,
                    )
            elif isinstance(result, list):
                # Если список — берём первый элемент
                result = result[0] if result else None
            elif result is None:
                logger.warning("Bitrix: get_deal(%s) вернул None", deal_id)
                return None
            else:
                logger.warning(
                    "Bitrix: get_deal(%s) вернул неожиданный тип: %s, значение: %s",
                    deal_id,
                    type(result),
                    result,
                )
                return None

            # Проверяем, что результат — это словарь с ключом "ID"
            if not isinstance(result, dict):
                logger.error(
                    "Bitrix: get_deal(%s) вернул не словарь после обработки. Тип: %s, значение: %s",
                    deal_id,
                    type(result),
                    result,
                )
                return None
            
            if "ID" not in result:
                logger.error(
                    "Bitrix: get_deal(%s) вернул словарь без ключа 'ID'. Ключи: %s, значение: %s",
                    deal_id,
                    list(result.keys()),
                    result,
                )
                return None

            logger.debug("Bitrix: get_deal(%s) → ID=%s", deal_id, result.get("ID"))
            return result
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
            # fast_bitrix24 может вернуть словарь с ключом "result" или список напрямую
            if isinstance(result, dict):
                # Если это словарь, возможно товары в result["result"] или result
                products = result.get("result", result)
                if isinstance(products, list):
                    return products
                elif isinstance(products, dict):
                    # Если это один товар в виде словаря, оборачиваем в список
                    return [products] if products else []
                else:
                    logger.warning(
                        "Bitrix: get_deal_products вернул неожиданный тип: %s, значение: %s",
                        type(products),
                        products,
                    )
                    return []
            elif isinstance(result, list):
                # Если это уже список — возвращаем как есть
                return result
            else:
                logger.warning(
                    "Bitrix: get_deal_products вернул неожиданный тип: %s, значение: %s",
                    type(result),
                    result,
                )
                return []
        except Exception:
            logger.exception(
                "Bitrix: ошибка получения товаров сделки %s", deal_id
            )
            return []

    async def get_all_deals(self, stage_id: str | None = None) -> List[Dict]:
        try:
            # Сначала пробуем найти все сделки в воронке Гидротех (CATEGORY_ID = 9)
            # Используем get_all() для методов .list, как рекомендует fast_bitrix24
            filter_dict = {
                "CATEGORY_ID": BITRIX_STAGES.CATEGORY_ID,
                "CLOSED": "N",
            }
            # Если указана стадия — добавляем фильтр
            if stage_id:
                filter_dict["STAGE_ID"] = stage_id
            
            result = await to_thread.run_sync(
                self.bx.get_all,
                "crm.deal.list",
                {
                    "filter": filter_dict,
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
            # get_all() всегда возвращает список
            deals = list(result) if result else []
            logger.info(
                "Bitrix: найдено %d незакрытых сделок в воронке %s",
                len(deals),
                BITRIX_STAGES.CATEGORY_ID,
            )
            
            # Если в воронке Гидротех ничего нет — пробуем все незакрытые сделки
            if not deals:
                logger.info(
                    "Bitrix: сделок в воронке %s не найдено, ищу все незакрытые сделки",
                    BITRIX_STAGES.CATEGORY_ID,
                )
                result = await to_thread.run_sync(
                    self.bx.get_all,
                    "crm.deal.list",
                    {
                        "filter": {
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
                # get_all() всегда возвращает список
                deals = list(result) if result else []
                logger.info(
                    "Bitrix: найдено %d незакрытых сделок (все воронки)",
                    len(deals),
                )
            
            return deals
        except Exception:
            logger.exception("Bitrix: error fetching all deals")
            return []

    async def create_deal(self, fields: Dict) -> Optional[int]:
        """
        Создаёт сделку в воронке Гидротех.
        fields — словарь полей Bitrix24 (TITLE, OPPORTUNITY, …).
        CATEGORY_ID и STAGE_ID подставляются автоматически, если не указаны.
        """
        fields.setdefault("CATEGORY_ID", BITRIX_STAGES.CATEGORY_ID)
        fields.setdefault("STAGE_ID", BITRIX_STAGES.NEW)
        fields.setdefault("CURRENCY_ID", "KZT")

        try:
            result = await to_thread.run_sync(
                self.bx.call,
                "crm.deal.add",
                {"fields": fields},
            )
            deal_id = int(result)
            logger.info(
                "Bitrix: сделка создана id=%s stage=%s",
                deal_id,
                fields["STAGE_ID"],
            )
            return deal_id
        except Exception:
            logger.exception("Bitrix: ошибка создания сделки")
            return None


    async def update_deal(self, deal_id: int, fields: Dict) -> bool:
        """Обновляет произвольные поля сделки."""
        try:
            await to_thread.run_sync(
                self.bx.call,
                "crm.deal.update",
                {"id": deal_id, "fields": fields},
            )
            logger.info("Bitrix: сделка %s обновлена, fields=%s", deal_id, list(fields.keys()))
            return True
        except Exception:
            logger.exception("Bitrix: ошибка обновления сделки %s", deal_id)
            return False

    async def update_deal_stage(self, deal_id: int, stage_id: str) -> bool:
        """
        Меняет стадию сделки с проверкой допустимого перехода.
        Если текущая стадия неизвестна (None или не в нашей карте) —
        обновляем принудительно с предупреждением.
        """
        deal = await self.get_deal(deal_id)
        if not deal:
            logger.error("Bitrix: сделка %s не найдена для смены стадии", deal_id)
            return False

        current_stage = deal.get("STAGE_ID")

        # Если текущая стадия известна — проверяем допустимость
        if current_stage and current_stage in BITRIX_STAGES.allowed_transitions:
            allowed = BITRIX_STAGES.allowed_transitions[current_stage]
            if stage_id not in allowed:
                logger.warning(
                    "Bitrix: запрещённый переход %s → %s для сделки %s. Допустимые: %s",
                    current_stage,
                    stage_id,
                    deal_id,
                    allowed,
                )
                return False
        else:
            # Стадия неизвестна или не в нашей карте — обновляем принудительно
            logger.warning(
                "Bitrix: текущая стадия '%s' сделки %s не распознана. "
                "Принудительно устанавливаю %s",
                current_stage,
                deal_id,
                stage_id,
            )

        return await self.update_deal(deal_id, {"STAGE_ID": stage_id})


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
            logger.info("Bitrix: товары сделки %s установлены (%d шт.)", deal_id, len(products))
            return True
        except Exception:
            logger.exception(
                "Bitrix: ошибка установки товаров для сделки %s", deal_id
            )
            return False
