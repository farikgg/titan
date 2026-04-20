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
        # Ищем существующий черновик для пользователя.
        # Раньше здесь использовался scalar_one_or_none(), что падало с MultipleResultsFound,
        # если по каким‑то причинам накопилось несколько черновиков.
        # Теперь безопасно берём первый найденный (самый старый) через .scalars().first().
        result = await self.db.execute(
            select(OfferModel).where(
                OfferModel.user_id == user_id,
                OfferModel.status == OfferStatus.DRAFT,
            )
        )
        offer = result.scalars().first()

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
                unit=price_obj.container_unit,  # Автоматическая подстановка ед. изм.
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
    # Update item (Change quantity, price, unit)
    # --------------------------------------------------

    async def update_item(
        self, offer_id: int, sku: str, quantity: float, price: float, unit: str | None = None
    ):
        """Обновляет количество, цену и единицу измерения (шт/кг) для выбранного товара."""
        offer = await self.db.get(OfferModel, offer_id)
        if not offer:
            raise ValueError("Offer not found")

        item = await self.db.scalar(
            select(OfferItemModel).where(
                OfferItemModel.offer_id == offer_id,
                OfferItemModel.sku == sku,
            )
        )

        if not item:
            raise ValueError("Item not found in offer")

        item.quantity = quantity
        item.price = Decimal(str(price))
        item.unit = unit
        item.total = item.price * Decimal(str(quantity))

        await self.recalc_total(offer_id)

        await self._log(
            actor_type="user",
            action="update_item",
            payload={
                "offer_id": offer_id,
                "sku": sku,
                "quantity": quantity,
                "price": price,
                "unit": unit,
            },
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
        # Добавляем новые поля условий
        payment_terms: str | None = None,
        delivery_terms: str | None = None,
        warranty_terms: str | None = None,
        # Поля для шапки
        manager_email: str | None = None,
        client_email: str | None = None,
        incoterms: str | None = None,
        deadline: str | None = None,
        delivery_place: str | None = None,
        notes: str | None = None,
        client_company_name: str | None = None,
        client_address: str | None = None,
        subject: str | None = None,
    ) -> OfferModel:
        """
        Создаёт корзину (Offer) для сделки из парсера писем.
        
        Args:
            deal_id: ID сделки в Bitrix24
            bitrix_user_id: Bitrix user ID ответственного менеджера
            items: список товаров [{"sku": "...", "name": "...", "price": 100.0, "quantity": 1, "found": True/False}]
            currency: валюта (если не указана, берётся из первого товара)
        """
        from src.repositories.user_repo import UserRepository
        
        # Находим пользователя по bitrix_user_id
        user_repo = UserRepository(self.db)
        user = await user_repo.get_by_bitrix_user_id(bitrix_user_id)
        
        if not user:
            logger.warning(
                "User with bitrix_user_id=%s not found, using default user_id=1",
                bitrix_user_id
            )
            user_id = 1
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
            logger.info("Updating existing offer %s", existing.id)
            offer = existing
        else:
            # Определяем валюту
            if not currency and items:
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

        # Обновляем условия КП, если они пришли
        if payment_terms: offer.payment_terms = payment_terms
        if delivery_terms: offer.delivery_terms = delivery_terms
        if warranty_terms: offer.warranty_terms = warranty_terms
        
        # Обновляем новые поля шапки
        if manager_email: offer.manager_email = manager_email
        if client_email: offer.client_email = client_email
        if incoterms: offer.incoterms = incoterms
        if deadline: offer.deadline = deadline
        if delivery_place: offer.delivery_place = delivery_place

        # Если есть заметки или даты, можем добавить их в конец условий или логировать
        if notes:
            current_notes = offer.payment_terms or ""
            if notes not in current_notes:
                offer.payment_terms = (current_notes + f"\nЗаметки: {notes}").strip()

        # Очищаем старые товары перед обновлением, если это существующий оффер
        if existing:
            await self.db.execute(
                delete(OfferItemModel).where(OfferItemModel.offer_id == offer.id)
            )

        # Добавляем товары в корзину
        from src.db.models.price_model import PriceModel
        
        for item_data in items:
            sku = item_data.get("sku") or item_data.get("art", "")
            name = item_data.get("name", "Товар не найден")
            raw_name = item_data.get("raw_name")
            price = Decimal(str(item_data.get("price") or 0))
            quantity = float(item_data.get("quantity", 1))
            unit = item_data.get("unit")
            found = item_data.get("found", False)

            # Ищем товар в прайсах для нормализованного имени
            price_obj = None
            if found:
                price_obj = await self.db.scalar(
                    select(PriceModel).where(PriceModel.art == sku)
                )

            current_name = price_obj.name if price_obj else name
            
            # Метаданные для фронтенда
            added_from = None
            reason = None
            confidence_level = None
            analog_id = None

            if not found:
                from src.repositories.analog_repo import AnalogRepository
                analog_repo = AnalogRepository()
                
                # 1. Поиск подтвержденных аналогов в БД
                analogs = await analog_repo.get_all_for_product(self.db, code=sku, name=name)
                
                if len(analogs) == 1:
                    analog = analogs[0]
                    # Автоподстановка
                    sku = analog.analog_product_code
                    current_name = f"[АНАЛОГ ИЗ БД] {analog.analog_product_name or analog.analog_product_code}"
                    
                    added_from = "db"
                    analog_id = analog.id

                    # Устанавливаем цену аналога, если он есть в прайсах
                    price_obj = await self.db.scalar(
                        select(PriceModel).where(PriceModel.art == sku)
                    )
                    if price_obj:
                        price = Decimal(str(price_obj.price))
                        if price_obj.container_unit:
                            unit = price_obj.container_unit
                    found = True
                else:
                    # 2. Если в БД нет (или их много), пробуем AI-поиск
                    from src.services.analog_ai_search import AnalogAISearch
                    ai_search_service = AnalogAISearch()
                    
                    brand_guess = item_data.get("brand")
                    ai_result = await ai_search_service.search(
                        self.db,
                        source_name=name,
                        source_code=sku,
                        source_brand=brand_guess
                    )
                    
                    if ai_result["status"] == "auto":
                        sku = ai_result["analog_product_code"]
                        current_name = f"[АНАЛОГ ИИ] {ai_result['analog_product_name'] or ai_result['analog_product_code']}"
                        
                        # Логирование: товар, кандидат, score, reason
                        logger.info(
                            "[АНАЛОГ ИИ] Товар: %s, Кандидат: %s, Score: %s, Reason: %s",
                            name, sku, ai_result["score"], ai_result["reason"]
                        )
                        
                        # Сохранять AI-найденный аналог в product_analogs со статусом new + added_from="ai"
                        analog_obj = None
                        try:
                            analog_obj = await analog_repo.create(
                                self.db,
                                source_art=item_data.get("sku") or sku,
                                analog_art=ai_result["analog_product_code"],
                                analog_name=ai_result["analog_product_name"],
                                analog_brand=ai_result["analog_brand"],
                                source_product_name=name,
                                source_brand=brand_guess,
                                confidence_level=ai_result["score"],
                                match_type=ai_result["match_type"],
                                status="new",
                                added_from="ai",
                                notes=ai_result["reason"]
                            )
                        except Exception as e:
                            logger.error("Failed to save AI analog to DB: %s", e)

                        # Заполняем метаданные для позиции оффера
                        added_from = "ai"
                        reason = ai_result.get("reason")
                        confidence_level = ai_result.get("score")
                        analog_id = analog_obj.id if analog_obj else None

                        # Устанавливаем цену аналога, если он есть в прайсах
                        price_obj = await self.db.scalar(
                            select(PriceModel).where(PriceModel.art == sku)
                        )
                        if price_obj:
                            price = Decimal(str(price_obj.price))
                            if price_obj.container_unit:
                                unit = price_obj.container_unit
                        found = True
                    elif len(analogs) > 1:
                        if not current_name.startswith("[НЕ НАЙДЕН"):
                            current_name = f"[НЕ НАЙДЕН - {len(analogs)} АНАЛОГОВ] {current_name}"
                    else:
                        if not current_name.startswith("[НЕ НАЙДЕН]"):
                            current_name = f"[НЕ НАЙДЕН] {current_name}"

            item = OfferItemModel(
                offer_id=offer.id,
                sku=sku or f"NOT_FOUND_{items.index(item_data)}",
                name=current_name,
                raw_name=raw_name,
                price=price,
                quantity=quantity,
                unit=unit,
                total=price * Decimal(str(quantity)),
                added_from=added_from,
                reason=reason,
                confidence_level=confidence_level,
                analog_id=analog_id,
            )
            self.db.add(item)

        # Пересчитываем итог
        await self.recalc_total(offer.id)

        # Telegram Notification
        try:
            from src.services.telegram_service import TelegramService, get_admin_chat_ids
            from src.app.config import settings
            import urllib.parse
            import logging

            tg = TelegramService()
            chat_ids = get_admin_chat_ids()
            if chat_ids:
                deal_title = subject or f"Сделка #{deal_id}"
                
                # Fetch items explicitly to avoid greenlet_spawn error on lazy local load
                from sqlalchemy import select
                from src.db.models.offer_item_model import OfferItemModel
                res = await self.db.execute(select(OfferItemModel).where(OfferItemModel.offer_id == offer.id))
                offer_items_loaded = res.scalars().all()

                lines = []
                has_not_found = False
                for item, item_model in zip(items, offer_items_loaded):
                    name_orig = item.get("name", "Без названия")
                    name = name_orig.replace("[НЕ НАЙДЕН] ", "")
                    if name_orig.startswith("[НЕ НАЙДЕН]"):
                        icon, suffix_text = "❌", "аналог не найден"
                        has_not_found = True
                    elif item_model.added_from in ("db", "ai"):
                        icon, suffix_text = "⚠️", f"[{str(item_model.added_from).upper()} АНАЛОГ] найден"
                    else:
                        icon, suffix_text = "✅", "найден в каталоге"

                    lines.append(f"{icon} {name} — {suffix_text}")
                
                items_str = "\n".join(lines)
                text = f"📋 Новая сделка #{deal_id} — \"{deal_title}\"\n\nТовары:\n{items_str}"

                domain = ""
                if settings.BITRIX_WEBHOOK:
                    parsed = urllib.parse.urlparse(settings.BITRIX_WEBHOOK)
                    domain = parsed.netloc
                bitrix_url = f"https://{domain}/crm/deal/details/{deal_id}/" if domain else ""

                keyboard = {"inline_keyboard": [[]]}
                url_btn = {"text": "📄 Открыть сделку", "url": bitrix_url} if bitrix_url else {"text": "📄 Открыть сделку", "callback_data": f"deal:{deal_id}"}
                keyboard["inline_keyboard"][0].append(url_btn)

                if has_not_found:
                    keyboard["inline_keyboard"][0].append({"text": "✉️ Запросить у Fuchs", "callback_data": f"request_analog:{offer.id}"})
                
                for cid in chat_ids:
                    await tg.send_message(chat_id=cid, text=text, keyboard=keyboard)
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("Failed to send telegram notification for deal %s: %s", deal_id, e)

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
        lead_time: str | None = None,
        currency: str | None = None,
        supplier_type: str | None = None,
        fuchs_margin_pct: float | None = None,
        fuchs_vat_enabled: bool | None = None,
        fuchs_vat_pct: float | None = None,
        skf_delivery_pct: float | None = None,
        skf_duty_pct: float | None = None,
        skf_margin_pct: float | None = None,
        skf_vat_enabled: bool | None = None,
        skf_vat_pct: float | None = None,
        client_company_name: str | None = None,
        client_address: str | None = None,
        subject: str | None = None,
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
        if lead_time is not None:
            offer.lead_time = lead_time
            changed = True
        if currency is not None:
            offer.currency = currency
            changed = True
        if client_company_name is not None:
            offer.client_company_name = client_company_name
            changed = True
        if client_address is not None:
            offer.client_address = client_address
            changed = True
        if subject is not None:
            offer.subject = subject
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
            if supplier_type == "fuchs":
                # FUCHS: (Purchase + 0.70) * 1.05 * (1 + Margin)
                delivery_per_kg = 0.70
                duty_pct_val = 5.0
                vat_pct_val = fuchs_vat_pct if fuchs_vat_pct is not None else 16.0
                vat_enabled = fuchs_vat_enabled if fuchs_vat_enabled is not None else True
                margin = fuchs_margin_pct if fuchs_margin_pct is not None else 50.0

                for item in items:
                    price_obj = await self.db.scalar(
                        select(PriceModel).where(
                            PriceModel.art == item.sku,
                            PriceModel.source == Source.FUCHS,
                        )
                    )
                    if not price_obj:
                        continue

                    purchase_price = float(price_obj.price)
                    # Формула из скриншота: (Закуп + 0.70) * 1.05 + (Закуп * Маржа)
                    landed_cost = (purchase_price + delivery_per_kg) * (1 + duty_pct_val / 100.0)
                    margin_amount = purchase_price * (margin / 100.0)
                    price_without_vat = landed_cost + margin_amount

                    if vat_enabled:
                        price_for_client = price_without_vat * (1 + vat_pct_val / 100.0)
                    else:
                        price_for_client = price_without_vat

                    item.price = Decimal(str(price_for_client))
                    item.total = item.price * Decimal(str(item.quantity))

                await self.recalc_total(offer_id)
                offer.vat_enabled = vat_enabled
                changed = True

            elif supplier_type == "skf":
                # SKF: (Purchase * 1.1 * 1.05) + (Purchase * Margin)
                delivery_pct_val = skf_delivery_pct if skf_delivery_pct is not None else 10.0
                duty_pct_val = skf_duty_pct if skf_duty_pct is not None else 5.0
                vat_pct_val = skf_vat_pct if skf_vat_pct is not None else 16.0
                vat_enabled = skf_vat_enabled if skf_vat_enabled is not None else True
                margin = skf_margin_pct if skf_margin_pct is not None else 50.0

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
                    # Формула из скриншота: (Закуп * 1.10 * 1.05) + (Закуп * Маржа)
                    landed_cost = (purchase_price * (1 + delivery_pct_val / 100.0)) * (1 + duty_pct_val / 100.0)
                    margin_amount = purchase_price * (margin / 100.0)
                    price_without_vat = landed_cost + margin_amount

                    if vat_enabled:
                        price_for_client = price_without_vat * (1 + vat_pct_val / 100.0)
                    else:
                        price_for_client = price_without_vat

                    item.price = Decimal(str(price_for_client))
                    item.total = item.price * Decimal(str(item.quantity))

                await self.recalc_total(offer_id)
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
                    "lead_time": lead_time,
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

    async def get_offer_by_bitrix_deal(self, deal_id: int | str):
        """
        Возвращает оффер (КП) и его товары по ID сделки Bitrix24.
        Используется для просмотра состава КП из карточки сделки.
        """
        deal_id_str = str(deal_id)

        result = await self.db.execute(
            select(OfferModel).where(
                OfferModel.bitrix_deal_id == deal_id_str
            )
        )
        offer = result.scalar_one_or_none()
        if not offer:
            return None

        items_result = await self.db.execute(
            select(OfferItemModel).where(
                OfferItemModel.offer_id == offer.id
            )
        )
        items = items_result.scalars().all()

        # Подгружаем статусы аналогов для фронтенда
        analog_ids = [i.analog_id for i in items if i.analog_id]
        analog_status_map = {}
        if analog_ids:
            from src.db.models.product_analog_model import ProductAnalogModel
            analog_res = await self.db.execute(
                select(ProductAnalogModel).where(ProductAnalogModel.id.in_(analog_ids))
            )
            analog_status_map = {a.id: a.status for a in analog_res.scalars().all()}

        return {
            "id": offer.id,
            "bitrix_deal_id": offer.bitrix_deal_id,
            "status": offer.status.value,
            "total": float(offer.total),
            "currency": offer.currency,
            "payment_terms": getattr(offer, "payment_terms", None),
            "delivery_terms": getattr(offer, "delivery_terms", None),
            "warranty_terms": getattr(offer, "warranty_terms", None),
            "lead_time": getattr(offer, "lead_time", None),
            "vat_enabled": getattr(offer, "vat_enabled", None),
            "items": [
                {
                    "sku": i.sku,
                    "name": i.name,
                    "price": float(i.price),
                    "quantity": i.quantity,
                    "total": float(i.total),
                    "added_from": i.added_from,
                    "reason": i.reason,
                    "confidence_level": i.confidence_level,
                    "analog_id": i.analog_id,
                    "analog_status": analog_status_map.get(i.analog_id) if i.analog_id else None,
                }
                for i in items
            ],
        }

    async def get_offer_with_items(self, offer_id: int):

        offer = await self.db.get(OfferModel, offer_id)

        result = await self.db.execute(
            select(OfferItemModel).where(
                OfferItemModel.offer_id == offer_id
            )
        )
        items = result.scalars().all()

        # Подгружаем статусы аналогов
        analog_ids = [i.analog_id for i in items if i.analog_id]
        analog_status_map = {}
        if analog_ids:
            from src.db.models.product_analog_model import ProductAnalogModel
            analog_res = await self.db.execute(
                select(ProductAnalogModel).where(ProductAnalogModel.id.in_(analog_ids))
            )
            analog_status_map = {a.id: a.status for a in analog_res.scalars().all()}

        return {
            "id": offer.id,
            "status": offer.status.value,
            "total": float(offer.total),
            "bitrix_deal_id": offer.bitrix_deal_id,
            "currency": offer.currency,
            "payment_terms": getattr(offer, "payment_terms", None),
            "delivery_terms": getattr(offer, "delivery_terms", None),
            "warranty_terms": getattr(offer, "warranty_terms", None),
            "lead_time": getattr(offer, "lead_time", None),
            "vat_enabled": getattr(offer, "vat_enabled", None),
            "items": [
                {
                    "sku": i.sku,
                    "name": i.name,
                    "price": float(i.price),
                    "quantity": i.quantity,
                    "total": float(i.total),
                    "added_from": i.added_from,
                    "reason": i.reason,
                    "confidence_level": i.confidence_level,
                    "analog_id": i.analog_id,
                    "analog_status": analog_status_map.get(i.analog_id) if i.analog_id else None,
                }
                for i in items
            ],
        }
