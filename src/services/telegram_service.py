import httpx, logging
from pathlib import Path
from src.app.config import settings

logger = logging.getLogger(__name__)


class TelegramService:
    def __init__(self):
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    async def send_message(self,chat_id: int, text: str, keyboard: dict | None = None):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    f"{self.base_url}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "reply_markup": keyboard,
                    },
                )
            logger.info("TELEGRAM ответ:", response.status_code, response.text)
            return response.json()
        except Exception as e:
            logger.exception(f"Ошибка при отправления сообщения: {e}")

    async def edit_message(self, chat_id: int, message_id: int, text: str, keyboard: dict | None = None):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"{self.base_url}/editMessageText",
                    json={
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "text": text,
                        "reply_markup": keyboard,
                    },
                )
        except Exception as e:
            logger.exception(f"Ошибка при редактирование сообщения: {e}")

    async def send_document(self, chat_id: int, file_path: Path, caption: str | None = None):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                with open(file_path, "rb") as f:
                    await client.post(
                        f"{self.base_url}/sendDocument",
                        data={
                            "chat_id": chat_id,
                            "caption": caption,
                        },
                        files={
                            "document": f
                        },
                    )
        except Exception as e:
            logger.exception(f"Ошибка при отправления документа: {e}")

    async def send_main_menu(self, chat_id: int):
        keyboard = {
            "inline_keyboard": [
                [{"text": "🛒 Моя корзина", "callback_data": "cart"}],
                [{"text": "➕ Добавить товар", "callback_data": "add"}],
                [{"text": "❌ Очистить", "callback_data": "clear"}],
                [{"text": "📄 Создать PDF", "callback_data": "pdf"}],
                [{"text": "🏢 Создать сделку", "callback_data": "convert"}],
                [{"text": "📚 История КП", "callback_data": "history"}],
            ]
        }

        return await self.send_message(
            chat_id,
            "Главное меню",
            keyboard,
        )

    async def send_pdf_menu(self, chat_id: int):
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "Сделка 123", "callback_data": "pdf:123"},
                    {"text": "Сделка 456", "callback_data": "pdf:456"},
                ],
                [
                    {"text": "⬅ Назад", "callback_data": "menu:main"}
                ],
            ]
        }
        return await self.send_message(
            chat_id,
            "Выберите сделку для генераций PDF:",
            keyboard,
        )
