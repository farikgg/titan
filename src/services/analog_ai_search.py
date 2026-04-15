# src/services/analog_ai_search.py

import json
import logging
import re
import asyncio
from google import genai
from google.genai import types
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, String

from src.app.config import settings
from src.repositories.analog_repo import normalize_code
from src.db.models.price_model import PriceModel

logger = logging.getLogger(__name__)

# --- КОНСТАНТЫ ---
SCORE_AUTO = 0.90      # выше → автоподстановка
SCORE_SUGGEST = 0.70   # выше → показать менеджеру
CATALOG_LIMIT = 50     # максимум кандидатов в промпт

SYSTEM_INSTRUCTION = """
Ты — эксперт по промышленным товарам и подбору аналогов.
Тебе дан ИСХОДНЫЙ ТОВАР и СПИСОК КАНДИДАТОВ из каталога.
Твоя задача — найти наилучший функциональный аналог из списка.

Критерии совместимости (по убыванию важности):
1. Артикул совпадает (точно или нормализованно — без дефисов/пробелов)
2. Один производитель + совпадение по названию
3. Технические характеристики совместимы (размеры, вязкость, давление и т.д.)
4. Область применения совпадает

Верни СТРОГО JSON без маркдауна:
{
    "found": true,
    "analog_product_code": "артикул из списка кандидатов",
    "analog_product_name": "название из списка кандидатов",
    "analog_brand": "бренд",
    "score": 0.95,
    "reason": "краткое объяснение почему это аналог (1-2 предложения)",
    "match_type": "exact_code | same_brand | functional"
}

Если подходящего аналога нет — верни:
{
    "found": false,
    "score": 0.0,
    "reason": "объяснение почему ни один кандидат не подходит"
}

Правила:
- score 0.90–1.0: прямая замена, автоподстановка допустима
- score 0.70–0.89: вероятный аналог, требует подтверждения менеджера
- score < 0.70: не подходит, вернуть found=false
- НЕ придумывай товары которых нет в списке кандидатов
- Если артикул совпадает после нормализации (убрать дефисы/пробелы/регистр) — score = 1.0
"""


class AnalogAISearch:

    def __init__(self):
        self.client = genai.Client(api_key=settings.GOOGLE_API_KEY)
        self.model = "gemini-2.0-flash"  # Используем Gemini 2.0 Flash

    # --- ПУБЛИЧНЫЙ МЕТОД ---
    async def search(
        self,
        db: AsyncSession,
        source_name: str | None,
        source_code: str | None,
        source_brand: str | None = None,
        source_specs: str | None = None,
    ) -> dict:
        """
        Главный метод. Возвращает:
        {
            "status": "auto" | "suggest" | "not_found",
            "analog_product_code": str | None,
            "analog_product_name": str | None,
            "analog_brand": str | None,
            "score": float,
            "reason": str,
            "match_type": str | None,
        }
        """
        # 1. Получить кандидатов из БД
        candidates = await self._get_candidates(db, source_code, source_brand)

        if not candidates:
            return self._not_found("Нет кандидатов в каталоге для данного бренда/артикула")

        # 2. Вызвать Gemini
        raw = await self._call_gemini(source_name, source_code, source_brand, source_specs, candidates)

        if not raw or not raw.get("found"):
            return self._not_found(raw.get("reason", "AI не нашёл подходящего аналога") if raw else "Ошибка AI")

        # 3. Определить статус по score
        score = raw.get("score", 0.0)
        status = "auto" if score >= SCORE_AUTO else "suggest"

        return {
            "status": status,
            "analog_product_code": raw.get("analog_product_code"),
            "analog_product_name": raw.get("analog_product_name"),
            "analog_brand": raw.get("analog_brand"),
            "score": score,
            "reason": raw.get("reason", ""),
            "match_type": raw.get("match_type"),
        }

    # --- ПРИВАТНЫЕ МЕТОДЫ ---

    async def _get_candidates(
        self, db: AsyncSession, source_code: str | None, source_brand: str | None
    ) -> list[dict]:
        """
        Достаём кандидатов из PriceModel (каталог).
        Фильтр: по бренду (source) или по нормализованному артикулу (art).
        """
        conditions = []

        if source_brand:
            # Ищем по бренду в поле source (FUCHS, SKF)
            conditions.append(PriceModel.source.cast(String).ilike(f"%{source_brand}%"))

        if source_code:
            norm = normalize_code(source_code)
            prefix = norm[:6] if len(norm) >= 4 else norm
            if prefix:
                # Ищем похожие артикулы (первые 6 символов для расширения выборки)
                conditions.append(PriceModel.art.ilike(f"%{prefix}%"))

        if not conditions:
            return []

        stmt = (
            select(PriceModel)
            .where(or_(*conditions))
            .limit(CATALOG_LIMIT)
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()

        return [
            {
                "code": r.art,
                "name": r.name,
                "brand": r.source.value if hasattr(r.source, 'value') else str(r.source),
                "specs": r.description or "",
            }
            for r in rows
        ]

    async def _call_gemini(
        self,
        source_name: str | None,
        source_code: str | None,
        source_brand: str | None,
        source_specs: str | None,
        candidates: list[dict],
    ) -> dict | None:
        """Вызов Gemini. Возвращает распарсенный JSON или None."""

        user_prompt = f"""ИСХОДНЫЙ ТОВАР:
Название: {source_name or 'не указано'}
Артикул: {source_code or 'не указан'}
Бренд: {source_brand or 'не указан'}
Доп. характеристики: {source_specs or 'не указаны'}

СПИСОК КАНДИДАТОВ ИЗ КАТАЛОГА ({len(candidates)} позиций):
{json.dumps(candidates, ensure_ascii=False, indent=2)}

Найди наилучший аналог. Верни только JSON."""

        raw_text = ""
        try:
            def _sync_call():
                return self.client.models.generate_content(
                    model=self.model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        temperature=0.1,
                        response_mime_type="application/json",
                    ),
                )

            response = await asyncio.to_thread(_sync_call)
            raw_text = response.text.strip()

            # Удаляем markdown-обёртку
            raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
            raw_text = re.sub(r"\s*```$", "", raw_text).strip()

            return json.loads(raw_text)

        except json.JSONDecodeError as e:
            logger.error(f"AnalogAISearch JSON decode error: {e} | raw: {raw_text[:200]}")
            return None
        except Exception as e:
            logger.error(f"AnalogAISearch Gemini error: {e}")
            return None

    @staticmethod
    def _not_found(reason: str) -> dict:
        return {
            "status": "not_found",
            "analog_product_code": None,
            "analog_product_name": None,
            "analog_brand": None,
            "score": 0.0,
            "reason": reason,
            "match_type": None,
        }
