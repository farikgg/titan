import httpx, logging
from pathlib import Path
from src.app.config import settings

logger = logging.getLogger(__name__)


class TelegramService:
    def __init__(self):
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    async def send_message(self,chat_id: int, text: str):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    f"{self.base_url}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "HTML",
                    },
                )
            print("TG RESPONSE:", response.status_code, response.text)
        except Exception as e:
            logger.exception(f"Ошибка при отправления сообщения: {e}")

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

    async def send_inline_keyboard(self, chat_id: int, text: str, keyboard: list[list[dict]]):
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "reply_markup": {
                        "inline_keyboard": keyboard,
                    }
                }
            )

    async def send_main_menu(self, chat_id: int):
        keyboard = [
            [
                {"text": "📄 Создать PDF", "callback_data": "menu:pdf"}
            ],
            [
                {"text": "🔄 Синхронизация FUCHS", "callback_data": "menu:sync"}
            ]
        ]

        await self.send_inline_keyboard(
            chat_id,
            "Главное меню:",
            keyboard
        )

    async def send_pdf_menu(self, chat_id: int):
        keyboard = [
            [
                {"text": "Сделка 123", "callback_data": "pdf:123"},
                {"text": "Сделка 456", "callback_data": "pdf:456"},
            ],
            [
                {"text": "⬅ Назад", "callback_data": "menu:main"}
            ]
        ]

        await self.send_inline_keyboard(
            chat_id,
            "Выберите сделку для генерации PDF:",
            keyboard
        )
