from decimal import Decimal
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models.offer_model import OfferModel, OfferStatus
from src.db.models.offer_item_model import OfferItemModel
from src.db.models.audit_log import AuditLog
from src.db.models.price_model import PriceModel, Source
import logging

logger = logging.getLogger(__name__)


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
    # Create offer for deal (from email parser)
    # --------------------------------------------------

    async def create_offer_for_deal(
        self,
        deal_id: int,
        bitrix_user_id: int,
        items: list[dict],
        currency: str | None = None,
    ) -> OfferModel:
        """
        Создаёт корзину (Offer) для сделки из парсера писем.
        
        Args:
            deal_id: ID сделки в Bitrix24
            bitrix_user_id: Bitrix user ID ответственного менеджера
            items: список товаров [{"sku": "...", "name": "...", "price": 100.0, "quantity": 1, "found": True/False}]
            currency: валюта (если не указана, берётся из первого товара)
        
        Returns:
            OfferModel: созданная корзина
        """
        from src.repositories.user_repo import UserRepository
        
        # Находим пользователя по bitrix_user_id
        user_repo = UserRepository(self.db)
        user = await user_repo.get_by_bitrix_user_id(bitrix_user_id)
        
        if not user:
            # Если пользователь не найден, используем дефолтного (DEFAULT_ASSIGNED_BY_ID = 109)
            # Ищем системного пользователя или создаём заглушку
            logger.warning(
                "User with bitrix_user_id=%s not found, using default user_id=1",
                bitrix_user_id
            )
            user_id = 1  # Дефолтный системный пользователь
        else:
            user_id = user.id

        # Проверяем, нет ли уже активной корзины для этой сделки
        existing = await self.db.scalar(
            select(OfferModel).where(
                OfferModel.bitrix_deal_id == str(deal_id),
                OfferModel.status == OfferStatus.DRAFT,
            )
        )

        if existing:
            logger.info(
                "Active offer already exists for deal_id=%s, offer_id=%s",
                deal_id,
                existing.id
            )
            return existing

        # Определяем валюту
        if not currency and items:
            # Пробуем взять из первого товара или дефолт
            currency = items[0].get("currency", "KZT")
        currency = currency or "KZT"

        # Создаём корзину
        offer = OfferModel(
            user_id=user_id,
            status=OfferStatus.DRAFT,
            total=Decimal("0.00"),
            currency=currency,
            bitrix_deal_id=str(deal_id),
        )
        self.db.add(offer)
        await self.db.flush()
        await self.db.refresh(offer)

        # Добавляем товары в корзину
        from src.db.models.price_model import PriceModel
        
        for item_data in items:
            sku = item_data.get("sku") or item_data.get("art", "")
            name = item_data.get("name", "Товар не найден")
            price = Decimal(str(item_data.get("price", 0)))
            quantity = int(item_data.get("quantity", 1))
            found = item_data.get("found", False)  # True если товар найден в прайсах

            # Если товар не найден, всё равно добавляем в корзину с пометкой
            if not found:
                # Добавляем как "не найден" - без привязки к PriceModel
                item = OfferItemModel(
                    offer_id=offer.id,
                    sku=sku or f"NOT_FOUND_{len(items)}",
                    name=f"[НЕ НАЙДЕН] {name}",
                    price=price,
                    quantity=quantity,
                    total=price * quantity,
                )
                self.db.add(item)
            else:
                # Ищем товар в прайсах
                price_obj = await self.db.scalar(
                    select(PriceModel).where(PriceModel.art == sku)
                )

                if price_obj:
                    # Товар найден в прайсах - добавляем нормально
                    item = OfferItemModel(
                        offer_id=offer.id,
                        sku=sku,
                        name=price_obj.name,
                        price=price_obj.price,
                        quantity=quantity,
                        total=price_obj.price * quantity,
                    )
                    self.db.add(item)
                else:
                    # Товар был помечен как найден, но в БД его нет - добавляем как "не найден"
                    item = OfferItemModel(
                        offer_id=offer.id,
                        sku=sku or f"NOT_FOUND_{len(items)}",
                        name=f"[НЕ НАЙДЕН] {name}",
                        price=price,
                        quantity=quantity,
                        total=price * quantity,
                    )
                    self.db.add(item)

        # Пересчитываем итог
        await self.recalc_total(offer.id)

        await self._log(
            actor_type="system",
            action="create_offer_for_deal",
            payload={"offer_id": offer.id, "deal_id": deal_id, "items_count": len(items)},
        )

        await self.db.commit()
        await self.db.refresh(offer)

        return offer

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
    # Terms (payment / delivery / warranty)
    # --------------------------------------------------

    async def update_terms(
        self,
        offer_id: int,
        *,
        payment_terms: str | None = None,
        delivery_terms: str | None = None,
        warranty_terms: str | None = None,
        supplier_type: str | None = None,
        fuchs_margin_pct: float | None = None,
        fuchs_vat_enabled: bool | None = None,
        fuchs_vat_pct: float | None = None,
        skf_delivery_pct: float | None = None,
        skf_duty_pct: float | None = None,
        skf_margin_pct: float | None = None,
        skf_vat_enabled: bool | None = None,
        skf_vat_pct: float | None = None,
    ):
        """
        Обновляет текстовые поля условий для КП.
        Любое поле можно не передавать — тогда оно не изменится.
        """
        offer = await self.db.get(OfferModel, offer_id)
        if not offer:
            raise ValueError("Offer not found")

        changed = False

        if payment_terms is not None:
            offer.payment_terms = payment_terms
            changed = True
        if delivery_terms is not None:
            offer.delivery_terms = delivery_terms
            changed = True
        if warranty_terms is not None:
            offer.warranty_terms = warranty_terms
            changed = True

        # --------------------------------------------------
        # Дополнительно: перерасчёт цен по формулам FUCHS / SKF
        # --------------------------------------------------
        if supplier_type:
            # Нормализуем тип
            supplier = supplier_type.lower()

            # Загружаем все позиции оффера
            result = await self.db.execute(
                select(OfferItemModel).where(OfferItemModel.offer_id == offer_id)
            )
            items = result.scalars().all()

            # Общие дефолты по НДС
            vat_default = 16.0

            if supplier == "fuchs":
                margin = fuchs_margin_pct if fuchs_margin_pct is not None else 50.0
                vat_enabled = bool(fuchs_vat_enabled) if fuchs_vat_enabled is not None else True
                vat_pct_val = fuchs_vat_pct if fuchs_vat_pct is not None else vat_default
                duty_pct_val = 5.0  # фикс
                delivery_per_kg = 0.70

                for item in items:
                    # Ищем цену FUCHS по артикулу
                    price_obj = await self.db.scalar(
                        select(PriceModel).where(
                            PriceModel.art == item.sku,
                            PriceModel.source == Source.FUCHS,
                        )
                    )
                    if not price_obj:
                        continue

                    purchase_price = float(price_obj.price)

                    base = purchase_price + delivery_per_kg
                    with_duty = base * (1 + duty_pct_val / 100.0)
                    price_without_vat = with_duty * (1 + margin / 100.0)

                    # Клиентская цена: с НДС, если он включён, иначе без НДС.
                    if vat_enabled:
                        price_for_client = price_without_vat * (1 + vat_pct_val / 100.0)
                    else:
                        price_for_client = price_without_vat

                    item.price = Decimal(str(price_for_client))
                    item.total = item.price * item.quantity

                await self.recalc_total(offer_id)
                # Сохраняем флаг НДС на уровне оффера для использования при генерации PDF.
                offer.vat_enabled = vat_enabled
                changed = True

            elif supplier == "skf":
                delivery_pct_val = skf_delivery_pct if skf_delivery_pct is not None else 10.0
                duty_pct_val = skf_duty_pct if skf_duty_pct is not None else 5.0
                margin = skf_margin_pct if skf_margin_pct is not None else 50.0
                vat_enabled = bool(skf_vat_enabled) if skf_vat_enabled is not None else True
                vat_pct_val = skf_vat_pct if skf_vat_pct is not None else vat_default

                for item in items:
                    price_obj = await self.db.scalar(
                        select(PriceModel).where(
                            PriceModel.art == item.sku,
                            PriceModel.source == Source.SKF,
                        )
                    )
                    if not price_obj:
                        continue

                    purchase_price = float(price_obj.price)

                    base = purchase_price * (1 + delivery_pct_val / 100.0)
                    with_duty = base * (1 + duty_pct_val / 100.0)
                    price_without_vat = with_duty * (1 + margin / 100.0)

                    # Клиентская цена: с НДС, если он включён, иначе без НДС.
                    if vat_enabled:
                        price_for_client = price_without_vat * (1 + vat_pct_val / 100.0)
                    else:
                        price_for_client = price_without_vat

                    item.price = Decimal(str(price_for_client))
                    item.total = item.price * item.quantity

                await self.recalc_total(offer_id)
                # Сохраняем флаг НДС на уровне оффера для использования при генерации PDF.
                offer.vat_enabled = vat_enabled
                changed = True

        if changed:
            await self._log(
                actor_type="user",
                action="update_terms",
                payload={
                    "offer_id": offer_id,
                    "payment_terms": payment_terms,
                    "delivery_terms": delivery_terms,
                    "warranty_terms": warranty_terms,
                    "supplier_type": supplier_type,
                },
            )
            await self.db.commit()

    # --------------------------------------------------
    # Convert
    # --------------------------------------------------

    async def convert_to_bitrix(
        self,
        offer_id: int,
        assigned_by_id: int | None = None,
        *,
        company_id: int | None = None,
        contact_id: int | None = None,
    ):
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

        # Если ответственный не передан — используем того же, что и для авто‑сделок FUCHS
        if assigned_by_id is None:
            from src.services.fuchs_pipeline import DEFAULT_ASSIGNED_BY_ID
            assigned_by_id = DEFAULT_ASSIGNED_BY_ID

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

        # Создаём сделку в Bitrix24 (стадия NEW → далее можем перевести в FINAL_INVOICE)
        deal_id = await deal_service.create_deal(
            title=f"КП #{offer.id}",
            assigned_by_id=assigned_by_id,
            currency=offer.currency or "KZT",
            company_id=company_id,
            contact_id=contact_id,
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
            "currency": offer.currency,
            # Эти поля могут отсутствовать в старых версиях модели/миграций,
            # поэтому берём их через getattr с дефолтом None.
            "payment_terms": getattr(offer, "payment_terms", None),
            "delivery_terms": getattr(offer, "delivery_terms", None),
            "warranty_terms": getattr(offer, "warranty_terms", None),
            "vat_enabled": getattr(offer, "vat_enabled", None),
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
