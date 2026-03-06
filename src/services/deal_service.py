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

        # Константы для пользовательских полей Bitrix в воронке «Гидротех.Сделки»
        # Выбор компании: TPG TITAN
        self._company_enum_tpg_titan = "62"  # UF_CRM_5B20F3A90BFCC

        # Справочник «Выберите решение»
        #   159 — Системы смазки
        #   161 — Смазочный материал
        #   163 — Системы пожаротушения
        self._solution_enum_map: Dict[str, str] = {
            "systems_lubrication": "159",
            "lubricant": "161",
            "fire_systems": "163",
        }

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

    async def create_deal_from_miniapp(
        self,
        *,
        title: str,
        company_id: int,
        stage_id: str,
        solution_code: str,
        amount: float,
        assigned_by_id: int,
    ) -> Optional[int]:
        """
        Создание сделки из Telegram Mini App в воронке «Гидротех.Сделки».

        Поля:
          - TITLE — название сделки
          - CATEGORY_ID = 9 — воронка «Гидротех.Сделки»
          - STAGE_ID — одна из стадий C9:*
          - COMPANY_ID — клиент (компания)
          - OPPORTUNITY — сумма сделки (из КП)
          - CURRENCY_ID — "KZT"
          - ASSIGNED_BY_ID — ответственный (из user.bitrix_user_id)
          - UF_CRM_5B20F3A90BFCC — выбор компании (TPG TITAN)
          - UF_CRM_1744862002484 — «Выберите решение»
        """
        solution_enum_id = self._solution_enum_map.get(solution_code)
        if not solution_enum_id:
            raise ValueError(
                f"Unknown solution code '{solution_code}'. "
                f"Ожидаю одно из: {list(self._solution_enum_map.keys())}"
            )

        fields: Dict[str, Any] = {
            "TITLE": title,
            "CATEGORY_ID": BITRIX_STAGES.CATEGORY_ID,
            "STAGE_ID": stage_id,
            "COMPANY_ID": company_id,
            "ASSIGNED_BY_ID": assigned_by_id,
            "CURRENCY_ID": "KZT",
            "OPPORTUNITY": float(amount),
            # Выбор компании: TPG TITAN
            "UF_CRM_5B20F3A90BFCC": self._company_enum_tpg_titan,
            # Выберите решение
            "UF_CRM_1744862002484": solution_enum_id,
        }

        deal_id = await self.bitrix.create_deal(fields)
        if not deal_id:
            return None

        logger.info(
            "DealService: мини‑апка создала сделку id=%s title=%s stage=%s company_id=%s",
            deal_id,
            title,
            stage_id,
            company_id,
        )
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
        """NEW → FINAL_INVOICE: договор заключен, сделка в работе."""
        return await self.bitrix.update_deal_stage(deal_id, BITRIX_STAGES.FINAL_INVOICE)

    async def move_to_kp_created(self, deal_id: int) -> bool:
        """FINAL_INVOICE → EXECUTING: этап АВР и накладной."""
        return await self.bitrix.update_deal_stage(deal_id, BITRIX_STAGES.EXECUTING)

    async def move_to_kp_sent(self, deal_id: int) -> bool:
        """EXECUTING → WON: КП/работы выполнены, сделка успешна."""
        return await self.bitrix.update_deal_stage(deal_id, BITRIX_STAGES.WON)

    async def move_to_won(self, deal_id: int) -> bool:
        """Прямой перевод в WON (Сделка успешна)."""
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
            logger.warning("DealService: сделка %s не найдена в Bitrix", deal_id)
            return None
        
        # Дополнительная проверка: убеждаемся, что deal - это словарь с нужными ключами
        if not isinstance(deal, dict):
            logger.error(
                "DealService: get_deal вернул не словарь для сделки %s. Тип: %s, значение: %s",
                deal_id,
                type(deal),
                deal,
            )
            return None
        
        if "ID" not in deal:
            logger.error(
                "DealService: сделка %s не содержит ключ 'ID'. Ключи: %s",
                deal_id,
                list(deal.keys()) if isinstance(deal, dict) else None,
            )
            return None

        products = await self.bitrix.get_deal_products(deal_id)

        # Безопасная обработка: проверяем, что products - это список словарей
        if not isinstance(products, list):
            logger.error(
                "DealService: get_deal_products вернул не список! Тип: %s, значение: %s",
                type(products),
                products,
            )
            products = []
        
        # Фильтруем только словари (игнорируем строки или другие типы)
        valid_products = [p for p in products if isinstance(p, dict)]
        
        skus = [p.get("PRODUCT_NAME", "") for p in valid_products]
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
            "products": valid_products,
            "resolved_prices": resolved_prices,
        }

    async def list_deals_for_user(self, user, stage_id: str | None = None) -> List[Dict]:
        """
        Row-level RBAC:
        - manager: только свои сделки (воронка Гидротех)
        - head-manager / admin: все сделки воронки

        На практике часто бывает, что bitrix_user_id ещё не проставлен
        или сделки созданы на другого ответственного. Чтобы у менеджера
        не была пустая страница, делаем фоллбек: если по ответственному
        ничего не нашли — показываем все сделки в воронке.
        """
        user_id = getattr(user, "id", None)
        user_role = getattr(user, "role", None)
        bitrix_user_id = getattr(user, "bitrix_user_id", None)
        
        logger.info(
            "DealService.list_deals_for_user: user_id=%s, role=%s, bitrix_user_id=%s",
            user_id,
            user_role,
            bitrix_user_id,
        )
        
        # Менеджер: сначала пробуем фильтр по ответственному
        if user.role == Role.manager.value:
            deals: List[Dict] = []

            if bitrix_user_id:
                logger.info(
                    "DealService: ищу сделки для менеджера с bitrix_user_id=%s, stage_id=%s",
                    bitrix_user_id,
                    stage_id,
                )
                deals = await self.bitrix.get_deals(
                    bitrix_user_id=bitrix_user_id,
                    stage_id=stage_id,
                )
                logger.info(
                    "DealService: найдено %d сделок для менеджера bitrix_user_id=%s",
                    len(deals),
                    bitrix_user_id,
                )

            # Если ничего не нашли (или bitrix_user_id нет) — фоллбек на все сделки
            if not deals:
                logger.warning(
                    "DealService: для manager id=%s (bitrix_user_id=%s) сделки не найдены, "
                    "возвращаю все сделки в воронке (stage_id=%s)",
                    user_id,
                    bitrix_user_id,
                    stage_id,
                )
                all_deals = await self.bitrix.get_all_deals(stage_id=stage_id)
                logger.info(
                    "DealService: фоллбек вернул %d сделок",
                    len(all_deals),
                )
                return all_deals

            return deals

        # Руководители / админы — сразу все сделки в воронке
        logger.info(
            "DealService: пользователь role=%s, возвращаю все сделки (stage_id=%s)",
            user_role,
            stage_id,
        )
        all_deals = await self.bitrix.get_all_deals(stage_id=stage_id)
        logger.info(
            "DealService: найдено %d сделок для role=%s",
            len(all_deals),
            user_role,
        )
        return all_deals
