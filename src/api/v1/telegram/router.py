from fastapi import APIRouter
from src.services.telegram_service import TelegramService
from src.worker.tasks import generate_pdf_task
from src.repositories.user_repo import UserRepository
from src.db.initialize import async_session

router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.post("/webhook")
async def telegram_webhook(update: dict):
    tg = TelegramService()

    # ---- callback ----
    callback = update.get("callback_query")
    if callback:
        data = callback["data"]
        chat_id = callback["message"]["chat"]["id"]

        # ---- MAIN MENU ----
        if data == "menu:main":
            await tg.send_main_menu(chat_id)
            return {"ok": True}

        # ---- PDF MENU ----
        if data == "menu:pdf":
            await tg.send_pdf_menu(chat_id)
            return {"ok": True}

        # ---- SYNC ----
        if data == "menu:sync":
            await tg.send_message(chat_id, "Синхронизация запущена")
            return {"ok": True}

        # ---- GENERATE PDF ----
        if data.startswith("pdf:"):
            deal_id = int(data.split(":")[1])

            generate_pdf_task.delay(deal_id, "PAID", chat_id)

            await tg.send_message(
                chat_id,
                f"⏳ Генерация PDF для сделки {deal_id} запущена"
            )

            return {"ok": True}

    # ---- message ----
    message = update.get("message")
    if not message:
        return {"ok": True}

    text = message.get("text", "")
    chat_id = message["chat"]["id"]
    tg_id = message["from"]["id"]

    async with async_session() as session:
        repo = UserRepository(session)
        user = await repo.get_by_tg_id(tg_id)


    # ---- /start ----
    if text.startswith("/start"):
        if not user:
            await tg.send_message(chat_id, "У вас нету доступа. Обратитесь к администратору.")
            return {"ok": True}

        await tg.send_main_menu(chat_id)
        print("TEXT:", text)
        print("USER:", user)
        return {"ok": True}

    # ---- /menu ----
    if text.startswith("/menu"):
        await tg.send_pdf_menu(chat_id)
        return {"ok": True}

    # ---- /pdf ----
    if text.startswith("/pdf"):
        parts = text.split()
        if len(parts) != 2:
            await tg.send_message(chat_id, "Формат: /pdf 123")
            return {"ok": True}

        deal_id = int(parts[1])
        generate_pdf_task.delay(deal_id, "PAID", chat_id)

        await tg.send_message(chat_id, f"Генерация PDF {deal_id} запущена")
        return {"ok": True}

    return {"ok": True}
