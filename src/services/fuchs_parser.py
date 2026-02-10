import json, logging, pdfplumber, pytesseract, os, pandas as pd
from json import JSONDecodeError

from docx import Document
from io import BytesIO
from groq import AsyncGroq
from PIL import Image, ImageOps
from pytesseract import TesseractNotFoundError

from src.app.config import settings
from src.schemas.price_schema import PriceCreate

logger = logging.getLogger(__name__)

class FuchsAIParser:
    def __init__(self):
        self.client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        self.model = "llama-3.3-70b-versatile"  # Самая мощная модель в Groq сейчас

        # Настройка пути к Tesseract, если он не в переменной окружения
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

                elif name.endswith(".docx"):
                    sheets = pd.read_excel(BytesIO(content), sheet_name=None)
                    for sheet_name, df in sheets.items():
                        df = df.rename(str.lower, axis=1)

                        required_cols = {
                            "sap number": "art",
                            "price €/piece": "price",
                        }
                        if not all(col in df.collumns for col in required_cols):
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
        Генерация структурированных данных через Groq
        """
        # Если текста вообще нет — не тратим токены
        if not email_body.strip() and not attachment_text.strip():
            return []

        MAX_TEXT_LEN = 15_000
        combined_text = f"EMAIL_BODY:\n{email_body}\n\nATTACHMENT_DATA:\n{attachment_text}"[:MAX_TEXT_LEN]
        logger.info("FUCHS парсер начал работать, длина текста:%s", len(combined_text))

        prompt = f"""
        SYSTEM ROLE:
        Ты — senior аналитик закупок и ценообразования в промышленной компании.

        КОНТЕКСТ:
        Документ — коммерческое предложение / quotation от поставщика FUCHS.
        Валюта документа: EUR, если не указано явно иное.

        ПРАВИЛА ИЗВЛЕЧЕНИЯ:
        - Извлекай ТОЛЬКО позиции товаров.
        - Каждая позиция ОБЯЗАНА иметь:
          - art (артикул или SAP Number или техническое обозначение)
          - name (название товара)
        - Цена может быть:
          - "XXX.XX"
          - "XXX,XX"
          - "XXX.XX / EA"
          Используй только числовое значение.
        - Если цена НЕ указана — ставь null.
        - Если валюта не указана явно — используй "EUR".
        - Игнорируй подписи, адреса, номера писем, условия поставки.

        ВАЖНО:
        - Если найден SAP Number — используй его как art.
        - Если SAP Number нет — используй FUCHS Alternative или техническое название.
        - НЕ придумывай цены.
        - НЕ дублируй позиции.

        ДАННЫЕ:
        --------------------
        {combined_text}
        --------------------

        ФОРМАТ ОТВЕТА:
        Верни ТОЛЬКО валидный JSON следующего вида:

        {{
          "items": [
            {{
              "art": "string",
              "name": "string",
              "price": number | null,
              "currency": "EUR"
            }}
          ]
        }}
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
