import json, logging, re
from google import genai
from google.genai import types

from src.app.config import settings
from src.repositories.analog_repo import AnalogRepository

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """
Ты — AI-ассистент отдела закупок.
Получено ответное письмо от поставщика на запрос подбора аналога.
Твоя задача — извлечь из текста письма ОДНУ связку "ИСХОДНЫЙ ТОВАР -> ПРЕДЛОЖЕННЫЙ АНАЛОГ".
Если поставщик предложил несколько аналогов, выбери самый релевантный.
Формат вывода СТРОГО JSON:
{
    "source_product_code": "артикул исходного запрошенного товара (если есть в тексте)",
    "analog_product_name": "полное название предложенного аналога",
    "analog_product_code": "артикул предложенного аналога (обязательно вытащи)",
    "analog_brand": "бренд аналога",
    "confidence_level": 0.9,
    "notes": "любые комментарии поставщика о замене"
}

Если в письме не предложено аналогов (отказ, нет в наличии и аналогов нет), верни:
{
    "analog_product_code": null
}
"""

class AnalogParser:
    def __init__(self):
        self.client = genai.Client(api_key=settings.GOOGLE_API_KEY)
        self.model = "gemini-3-flash-preview"

    async def parse_analog_reply(self, email_body: str, subject: str) -> dict:
        combined_text = f"SUBJECT:\n{subject}\n\nEMAIL_BODY:\n{email_body}"[:15000]

        user_prompt = f"""
        Извлеки предложенный аналог и верни JSON.
        ДАННЫЕ:
        {combined_text}
        """

        try:
            import asyncio
            def _sync_api_call():
                return self.client.models.generate_content(
                    model=self.model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        temperature=0.1,
                        response_mime_type="application/json",
                    ),
                )
            
            response = await asyncio.to_thread(_sync_api_call)
            raw_response = response.text
            
            # Удаляем маркдаун обёртку, если она есть
            raw_response = raw_response.strip()
            if raw_response.startswith("```"):
                raw_response = re.sub(r"^```(?:json)?\s*", "", raw_response)
                raw_response = re.sub(r"\s*```$", "", raw_response)
                raw_response = raw_response.strip()
                
            try:
                raw_json = json.loads(raw_response)
                return raw_json
            except json.JSONDecodeError:
                logger.error(f"Ошибка JSON при парсинге аналога: {raw_response}")
                return {}

        except Exception as e:
            logger.error(f"Ошибка AI Аналог парсера: {e}")
            return {}

    async def process_analog_reply(self, db, message_dict: dict):
        """
        Прогоняет письмо через ИИ и сохраняет в БД с ожиданием подтверждения
        """
        subject = message_dict.get("subject", "")
        body = message_dict.get("body", "") or message_dict.get("bodyPreview", "")
        message_id = message_dict.get("message_ids", "")

        parsed_data = await self.parse_analog_reply(body, subject)
        
        analog_code = parsed_data.get("analog_product_code")
        if not analog_code:
            logger.info("Аналог не найден в ответном письме.")
            return None
            
        repo = AnalogRepository()
        
        # Попытаемся вытащить исходный артикул из темы, если ИИ его не нашел
        # Темы отправляются как "Запрос аналога: Название (art: 12345)"
        source_art = parsed_data.get("source_product_code")
        if not source_art:
            match = re.search(r'\(art:\s*([^)]+)\)', subject)
            if match:
                source_art = match.group(1)
        
        if not source_art:
            source_art = "UNKNOWN"
            
        analog = await repo.create(
            db,
            source_art=source_art,
            analog_art=analog_code,
            analog_name=parsed_data.get("analog_product_name"),
            analog_brand=parsed_data.get("analog_brand"),
            confidence_level=parsed_data.get("confidence_level"),
            notes=parsed_data.get("notes"),
            status="new", # ЖДЕТ ПОДТВЕРЖДЕНИЯ
            email_thread_id=message_id,
        )
        return analog
