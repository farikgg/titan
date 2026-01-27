import json, logging, pdfplumber, pytesseract, pandas as pd
from json import JSONDecodeError

from docx import Document
from io import BytesIO
from groq import AsyncGroq
from PIL import Image, ImageOps

from src.app.config import settings
from src.schemas.price_schema import PriceCreate

logger = logging.getLogger(__name__)

class FuchsAIParser:
    def __init__(self):
        self.client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        self.model = "llama-3.3-70b-versatile"  # Самая мощная модель в Groq сейчас

    # Настройка пути к Tesseract, если он не в переменной окружения
    # import os
    # pytesseract.pytesseract.tesseract_cmd = os.getenv('TESSERACT_CMD', 'tesseract')

    async def is_not_spam(self, subject: str, body: str) -> bool:
        """
        Фильтрация. Проверяем, является ли письмо запросом цены/КП
        """
        stop_words = ["акция", "распродажа", "reklama", "survey", "advertisement", "реклама", "опрос"]
        if any(word in subject.lower() for word in stop_words) or any(word in body.lower() for word in stop_words):
            return False
        return True

    def extract_text_from_attachments(self, attachments: list[dict]) -> str:
        """
        Извлечение текста из файлов.
        attachments: список словарей {'name': str, 'content': bytes, 'mime_type': str}
        """
        full_text = ""

        for att in attachments:
            content = att['content']
            name = att['name'].lower()
            file_text = f"\n--- ФАЙЛ: {name} ---\n"

            try:
                # PDF
                if name.endswith('.pdf'):
                    with pdfplumber.open(BytesIO(content)) as pdf:
                        file_text += "\n".join(page.extract_text() for page in pdf.pages if page.extract_text())
                # WORD
                elif name.endswith('.docx'):
                    doc = Document(BytesIO(content))
                    file_text += "\n".join(p.text for p in doc.paragraphs)
                # EXCEL sheets
                elif name.endswith(('.xls', '.xlsx')):
                    df = pd.read_excel(BytesIO(content))
                    file_text += df.to_string()
                # IMAGES
                elif name.endswith (('.jpg', '.jpeg', '.png', '.bmp', '.webp')):
                    image = Image.open(BytesIO(content))

                    # --- ПРЕПРОЦЕССИНГ (Делаем ч/б и контраст для лучшего OCR) ---
                    image = image.convert('L') # В ч/б
                    image = ImageOps.autocontrast(image) # Повышаем контраст
                    # -------------------------------------------------------------

                    file_text += pytesseract.image_to_string(image, lang='rus+kaz+eng')

                full_text += file_text
            except Exception as e:
                logger.error(f"❌ Ошибка парсинга {name}: {e}")
        return full_text

    async def parse_to_objects(self, email_body: str, attachment_text: str = "") -> list[PriceCreate]:
        """
        Генерация структурированных данных через Groq
        """
        # Если текста вообще нет — не тратим токены
        if not email_body.strip() and not attachment_text.strip():
            return []

        combined_text = f"EMAIL_BODY:\n{email_body}\n\nATTACHMENT_DATA:\n{attachment_text}"

        prompt = f"""
        Ты — ведущий аналитик ГК Титан. Твоя задача: извлечь прайс-лист из данных поставщика FUCHS.

        ИНСТРУКЦИИ:
        1. Извлеки артикул (art), название (name), цену (price) и валюту (currency).
        2. Если цена указана со скидкой, бери финальную цену.
        3. Валюту приводи к стандарту ISO (RUB, EUR, USD).
        4. Игнорируй нерелевантную информацию (адреса, подписи).

        ДАННЫЕ ДЛЯ АНАЛИЗА:
        {combined_text}

        ФОРМАТ ОТВЕТА: Только JSON объект с ключом "items".
        Пример: {{"items": [{{"art": "123", "name": "Oil", "price": 100.5, "currency": "EUR", "description": "..."}}]}}
        """

        try:
            response = await self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
                temperature=0,  # Для точности данных ставим 0
                response_format={"type": "json_object"}
            )

            raw_response = response.choices[0].message.content
            logger.info("=== RAW GROQ RESPONSE START ===")
            logger.info(raw_response)
            logger.info("=== RAW GROQ RESPONSE END ===")

            try:
                raw_json = json.loads(raw_response)
            except JSONDecodeError as e:
                logger.error(f"Ошибка парсинга, сырой ответ {raw_response}")
                return []

            items = raw_json.get("items", [])

            validated_items = []
            for item in items:
                try:
                    # Принудительно ставим источник
                    item.update({"source": "fuchs", "source_type": "email"})
                    # Валидация Pydantic
                    validated_items.append(PriceCreate(**item))
                except Exception as ve:
                    logger.warning(f"⚠️ Пропуск товара из-за ошибки валидации: {ve} | Данные: {item}")

            return validated_items

        except Exception as e:
            logger.error(f"🔥 Критическая ошибка ИИ-парсера: {e}")
            return []