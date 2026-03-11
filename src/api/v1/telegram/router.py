from fastapi import APIRouter
from sqlalchemy import select

from src.services.telegram_service import TelegramService
from src.services.deal_service import DealService
from src.services.bitrix_service import BitrixService
from src.core.bitrix import get_bitrix_client
from src.worker.tasks import generate_offer_pdf_task
from src.repositories.user_repo import UserRepository
from src.services.offer_service import OfferService
from src.db.models.price_model import PriceModel
from src.db.models.offer_model import OfferModel
from src.core.enums import Role
from src.app.config import BITRIX_STAGES

from src.db.initialize import async_session
from src.worker.tasks import parse_from_fuchs, parse_from_requests, sync_skf_prices_task

router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.post("/webhook")
async def telegram_webhook(update: dict):
    tg = TelegramService()

    # =========================
    # CALLBACK
    # =========================
    callback = update.get("callback_query")
    if callback:
        data = callback["data"]
        chat_id = callback["message"]["chat"]["id"]
        message_id = callback["message"]["message_id"]
        tg_id = callback["from"]["id"]

        async with async_session() as session:
            repo = UserRepository(session)
            user = await repo.get_by_tg_id(tg_id)

            if not user:
                await tg.edit_message(chat_id, message_id, "Нет доступа", tg.back_button())
                return {"ok": True}

            offer_service = OfferService(session)
            offer = await offer_service.get_or_create_draft(user.id)

            # ---------------- MAIN MENU ----------------
            if data == "menu:main":
                keyboard = [
                    [{"text": "🛒 Моя корзина", "callback_data": "cart"}],
                    [{"text": "➕ Добавить товар", "callback_data": "add"}],
                    [{"text": "❌ Очистить", "callback_data": "clear"}],
                    [{"text": "📄 Создать PDF", "callback_data": "generate"}],
                    [{"text": "🏢 Создать сделку", "callback_data": "convert"}],
                    [{"text": "📨 Отметить КП отправленным", "callback_data": "mark_kp_sent"}],
                    [{"text": "📚 История КП", "callback_data": "history"}],
                ]

                # --- sync кнопки только для админа ---
                if user.role in (Role.admin.value, Role.head_manager.value):
                    keyboard.append(
                        [{"text": "📬 Синхронизация FUCHS", "callback_data": "sync:fuchs"}]
                    )
                    keyboard.append(
                        [{"text": "🔄 Синхронизация SKF", "callback_data": "sync:skf"}]
                    )

                return await tg.edit_message(
                    chat_id,
                    message_id,
                    "Главное меню — Воронка Гидротех",
                    {"inline_keyboard": keyboard},
                )

            # ---------------- ADD MENU ----------------
            if data == "add":
                result = await session.execute(select(PriceModel).limit(5))
                prices = result.scalars().all()

                keyboard = [
                    [
                        {
                            "text": f"{p.art} | {p.price}",
                            "callback_data": f"add:{p.art}",
                        }
                    ]
                    for p in prices
                ]

                keyboard.append(
                    [{"text": "⬅ Назад", "callback_data": "menu:main"}]
                )

                return await tg.edit_message(
                    chat_id,
                    message_id,
                    "Выберите товар:",
                    {"inline_keyboard": keyboard},
                )

            if data == "sync:fuchs":
                if user.role not in (Role.admin.value, Role.head_manager.value):
                    return await tg.edit_message(chat_id, message_id, "Нет доступа", tg.back_button())

                parse_from_fuchs.delay()
                return await tg.edit_message(
                    chat_id,
                    message_id,
                    "📬 FUCHS парсинг запущен",
                    {
                        "inline_keyboard": [
                            [{"text": "⬅ Назад", "callback_data": "menu:main"}]
                        ]
                    },
                )

            if data == "sync:requests":
                if user.role not in (Role.admin.value, Role.head_manager.value):
                    return await tg.edit_message(chat_id, message_id, "Нет доступа", tg.back_button())

                parse_from_requests.delay()
                return await tg.edit_message(
                    chat_id,
                    message_id,
                    "📧 Парсинг Requests запущен\nСоздание сделок и корзин...",
                    {
                        "inline_keyboard": [
                            [{"text": "⬅ Назад", "callback_data": "menu:main"}]
                        ]
                    },
                )

            if data == "sync:skf":
                if user.role not in (Role.admin.value, Role.head_manager.value):
                    return await tg.edit_message(chat_id, message_id, "Нет доступа", tg.back_button())

                sync_skf_prices_task.delay()
                return await tg.edit_message(
                    chat_id,
                    message_id,
                    "🔄 SKF sync запущен",
                    {
                        "inline_keyboard": [
                            [{"text": "⬅ Назад", "callback_data": "menu:main"}]
                        ]
                    }
                )

            # ---------------- ADD ITEM ----------------
            if data.startswith("add:"):
                sku = data.split(":")[1]

                await offer_service.add_item(offer.id, sku)
                await session.commit()

                return await tg.edit_message(
                    chat_id,
                    message_id,
                    f"✅ {sku} добавлен",
                    {
                        "inline_keyboard": [
                            [{"text": "🛒 Открыть корзину", "callback_data": "cart"}],
                            [{"text": "⬅ Назад", "callback_data": "menu:main"}],
                        ]
                    },
                )

            # ---------------- CART ----------------
            if data == "cart":
                result = await offer_service.get_offer_with_items(offer.id)

                if not result["items"]:
                    return await tg.edit_message(
                        chat_id,
                        message_id,
                        "🛒 Корзина пуста",
                        tg.back_button()
                    )

                text = "🛒 Твоя корзина:\n\n"

                for item in result["items"]:
                    text += f"{item['name']}\n"
                    text += f"{item['price']} x {item['quantity']} = {item['total']}\n\n"

                text += f"💰 Итого: {result['total']}"

                return await tg.edit_message(chat_id, message_id, text, tg.back_button())

            # ---------------- CLEAR ----------------
            if data == "clear":
                await offer_service.clear_offer(offer.id)
                await session.commit()

                return await tg.edit_message(
                    chat_id,
                    message_id,
                    "🧹 Корзина очищена",
                )

            # ---------------- GENERATE PDF ----------------
            if data == "generate":
                generate_offer_pdf_task.delay(offer.id, chat_id)

                return await tg.edit_message(
                    chat_id,
                    message_id,
                    "⏳ Генерация PDF запущена",
                    tg.back_button()
                )

            # ---------------- CONVERT ----------------
            if data == "convert":
                try:
                    deal_id = await offer_service.convert_to_bitrix(
                        offer.id,
                        assigned_by_id=user.bitrix_user_id,
                    )
                    await session.commit()

                    return await tg.edit_message(
                        chat_id,
                        message_id,
                        f"🏢 Сделка создана в воронке Гидротех\n"
                        f"ID: {deal_id}\n"
                        f"Стадия: Подготовка КП",
                        {
                            "inline_keyboard": [
                                [{"text": "📄 Создать PDF", "callback_data": "generate"}],
                                [{"text": "⬅ Назад", "callback_data": "menu:main"}],
                            ]
                        },
                    )
                except ValueError as e:
                    return await tg.edit_message(
                        chat_id,
                        message_id,
                        f"⚠️ {e}",
                        tg.back_button(),
                    )

            # ---------------- KP_SENT (отметить отправку КП) ----------------
            if data == "mark_kp_sent":
                offer = await offer_service.get_or_create_draft(user.id)
                bitrix_deal_id = offer.bitrix_deal_id

                if not bitrix_deal_id:
                    return await tg.edit_message(
                        chat_id, message_id,
                        "⚠️ Сделка не привязана к Bitrix",
                        tg.back_button(),
                    )

                bx = get_bitrix_client()
                deal_service = DealService(BitrixService(bx))
                success = await deal_service.move_to_kp_sent(int(bitrix_deal_id))

                if success:
                    return await tg.edit_message(
                        chat_id, message_id,
                        f"📨 КП отправлено клиенту\nСделка #{bitrix_deal_id} → КП отправлено",
                        tg.back_button(),
                    )
                else:
                    return await tg.edit_message(
                        chat_id, message_id,
                        "⚠️ Невозможно сменить стадию. Сначала сгенерируйте PDF.",
                        tg.back_button(),
                    )

            # ---------------- DEAL STAGES (управление стадией) ----------------
            if data.startswith("stage:"):
                parts = data.split(":")
                if len(parts) == 3:
                    target_deal_id = int(parts[1])
                    target_stage = parts[2]

                    bx = get_bitrix_client()
                    deal_service = DealService(BitrixService(bx))

                    stage_handlers = {
                        "preparation": deal_service.move_to_preparation,
                        "kp_created": deal_service.move_to_kp_created,
                        "kp_sent": deal_service.move_to_kp_sent,
                        "won": deal_service.move_to_won,
                        "lost": deal_service.move_to_lost,
                    }

                    handler = stage_handlers.get(target_stage)
                    if handler:
                        success = await handler(target_deal_id)
                        status_text = "✅ Стадия обновлена" if success else "⚠️ Переход невозможен"
                    else:
                        status_text = "⚠️ Неизвестная стадия"

                    return await tg.edit_message(
                        chat_id, message_id,
                        f"{status_text}\nСделка: #{target_deal_id}",
                        tg.back_button(),
                )

            # ---------------- HISTORY ----------------
            if data == "history":
                offers = await offer_service.get_user_offers(user.id)

                if not offers:
                    return await tg.edit_message(
                        chat_id,
                        message_id,
                        "У вас пока нет КП",
                        tg.back_button()
                    )

                text = "📚 История КП:\n\n"

                for o in offers:
                    text += (
                        f"КП #{o['id']} | "
                        f"{o['status']} | "
                        f"{o['total']} | "
                        f"Deal: {o['bitrix_deal_id']}\n"
                    )

                return await tg.edit_message(chat_id, message_id, text, tg.back_button())

        return {"ok": True}

    # =========================
    # MESSAGE
    # =========================
    message = update.get("message")
    if not message:
        return {"ok": True}

    text = message.get("text", "")
    chat_id = message["chat"]["id"]
    tg_id = message["from"]["id"]

    async with async_session() as session:
        repo = UserRepository(session)
        user = await repo.get_by_tg_id(tg_id)

    if text.startswith("/start"):
        if not user:
            await tg.send_message(
                chat_id,
                "Нет доступа. Обратитесь к администратору.",
            )
            return {"ok": True}

        keyboard = [
            [{"text": "🛒 Моя корзина", "callback_data": "cart"}],
            [{"text": "➕ Добавить товар", "callback_data": "add"}],
            [{"text": "❌ Очистить", "callback_data": "clear"}],
            [{"text": "📄 Создать PDF", "callback_data": "generate"}],
            [{"text": "🏢 Создать сделку", "callback_data": "convert"}],
            [{"text": "📨 Отметить КП отправленным", "callback_data": "mark_kp_sent"}],
            [{"text": "📚 История КП", "callback_data": "history"}],
        ]

        if user.role in (Role.admin.value, Role.head_manager.value):
            keyboard.append(
                [{"text": "📬 Синхронизация FUCHS", "callback_data": "sync:fuchs"}]
            )
            keyboard.append(
                [{"text": "📧 Парсинг Requests", "callback_data": "sync:requests"}]
            )
            keyboard.append(
                [{"text": "🔄 Синхронизация SKF", "callback_data": "sync:skf"}]
            )

        await tg.send_message(
            chat_id,
            "Главное меню — Воронка Гидротех",
            {"inline_keyboard": keyboard},
        )

        return {"ok": True}

    return {"ok": True}
