import json, logging, pdfplumber, pytesseract, os, pandas as pd
from json import JSONDecodeError

from io import BytesIO
from google import genai
from google.genai import types
from PIL import Image, ImageOps
from pytesseract import TesseractNotFoundError

from src.app.config import settings
from src.schemas.price_schema import PriceCreate

logger = logging.getLogger(__name__)

# ── System instruction (роль + правила) — отделяем от данных ──
SYSTEM_INSTRUCTION = """
Ты — senior аналитик закупок и ценообразования в промышленной компании.

КОНТЕКСТ:
Это коммерческое предложение (quotation) от поставщика FUCHS.
Если валюта не указана явно — считай, что валюта EUR.

ЗАДАЧА:
Извлечь ТОЛЬКО товарные позиции.

ОБЯЗАТЕЛЬНЫЕ ПОЛЯ ДЛЯ КАЖДОЙ ПОЗИЦИИ:
- art (артикул)
- name (название)

ПРАВИЛА:
1. Если найден SAP Number — используй его как art.
2. Если SAP Number отсутствует:
   - используй техническое название или FUCHS Alternative
   - используй его и как art, и как name.
3. Поле "art" НИКОГДА не может быть null или пустым.
4. Цена:
   - может быть вида "123.45", "123,45", "123.45 / EA"
   - используй только числовое значение
   - если цены нет — ставь null
5. Валюта:
   - если явно не указана — используй "EUR"
6. НЕ:
   - придумывай цены
   - дублируй позиции
   - извлекай подписи, адреса, условия поставки

ФОРМАТ ОТВЕТА:
Верни ТОЛЬКО валидный JSON строго в этом формате:

{
  "items": [
    {
      "art": "string",
      "name": "string",
      "price": number | null,
      "currency": "EUR"
    }
  ]
}
""".strip()


class FuchsAIParser:
    def __init__(self):
        self.client = genai.Client(api_key=settings.GOOGLE_API_KEY)
        self.model = "gemini-3-flash-preview"

        # Настройка пути к Tesseract, если он не в переменной окружении
        tesseract_cmd = os.getenv("TESSERACT_CMD")
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    def is_not_spam(self, subject: str, body: str) -> bool:
        """
        Фильтрация. Проверяем, является ли письмо запросом цены/КП
        """
        spam_keywords = {
            "акция", "распродажа", "advertisement", "survey", "опрос"
        }

        text = f"{subject} {body}".lower()
        spam_hits = sum(1 for w in spam_keywords if w in text)

        return spam_hits < 2

    def extract_text_from_attachments(self, attachments: list[dict]) -> str:
        """
        Извлечение текста из файлов.
        attachments: список словарей {'name': str, 'content': bytes, 'mime_type': str}
        """
        full_text = ""

        for att in attachments:
            name = att["name"].lower()
            content = att["content"]
            file_text = f"\n--- FILE: {name} ---\n"

            try:
                if name.endswith(".pdf"):
                    with pdfplumber.open(BytesIO(content)) as pdf:
                        for page in pdf.pages:
                            text = page.extract_text()
                            if text:
                                file_text += text + "\n"

                elif name.endswith(".xlsx"):
                    sheets = pd.read_excel(BytesIO(content), sheet_name=None)
                    for sheet_name, df in sheets.items():
                        df = df.rename(str.lower, axis=1)

                        required_cols = {
                            "sap number": "art",
                            "price €/piece": "price",
                        }
                        if not all(col in df.columns for col in required_cols):
                            continue
                        for _, row in df.iterrows():
                            art = str(row["sap number"]).strip()
                            price = str(row["price €/piece"]).replace(",", ".").strip()

                            if not art or not price:
                                continue

                            file_text += (
                                f"\nITEM:\n"
                                f"art: {art}\n"
                                f"price: {price}\n"
                                f"currency: EUR\n"
                            )

                elif name.endswith((".xls", ".xlsx")):
                    sheets = pd.read_excel(BytesIO(content), sheet_name=None)
                    for sheet_name, df in sheets.items():
                        file_text += f"\n[SHEET: {sheet_name}]\n"
                        file_text += df.to_csv(sep=";", index=False)

                elif name.endswith((".jpg", ".jpeg", ".png", ".bmp", ".webp")):
                    try:
                        image = Image.open(BytesIO(content))
                        image = image.convert("L")
                        image = image.resize(
                            (image.width * 2, image.height * 2),
                            Image.BICUBIC,
                        )
                        image = ImageOps.autocontrast(image)

                        file_text += pytesseract.image_to_string(
                            image, lang="rus+kaz+eng"
                        )
                    except TesseractNotFoundError:
                        logger.warning("OCR отключен, пропускаю изображение %s", name)

                full_text += file_text

            except Exception as e:
                logger.exception(f"Ошибка парсинга файла {name}: {e}")

        return full_text

    async def parse_to_objects(self, email_body: str, attachment_text: str = "") -> list[PriceCreate]:
        """
        Генерация структурированных данных через Google Gemini
        """
        # Если текста вообще нет — не тратим токены
        if not email_body.strip() and not attachment_text.strip():
            return []

        MAX_TEXT_LEN = 15_000
        combined_text = f"EMAIL_BODY:\n{email_body}\n\nATTACHMENT_DATA:\n{attachment_text}"[:MAX_TEXT_LEN]
        logger.info("FUCHS парсер начал работать, длина текста:%s", len(combined_text))

        user_prompt = f"""
ДАННЫЕ:
--------------------
{combined_text}
--------------------

Извлеки товарные позиции из данных выше и верни JSON.
""".strip()

        try:
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0,  # Для точности данных ставим 0
                    response_mime_type="application/json",
                ),
            )

            raw_response = response.text
            logger.info("=== RAW GEMINI RESPONSE START ===")
            logger.info(raw_response)
            logger.info("=== RAW GEMINI RESPONSE END ===")

            try:
                raw_json = json.loads(raw_response)
            except JSONDecodeError as e:
                logger.error(f"Ошибка парсинга, сырой ответ {raw_response}")
                return []

            items = raw_json.get("items") or []
            if not isinstance(items, list):
                return []

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
