"""
нам нужно защитить backend, чтобы только TMA мог запрашивать цены
"""
import hmac, hashlib

from fastapi import Header, HTTPException, status
from urllib.parse import parse_qsl

from src.app.config import settings


def verify_telegram_data(init_data: str, bot_token: str) -> bool:
    try:
        # 1. Парсим строку запроса в словарь
        vals = dict(parse_qsl(init_data))
        if "hash" not in vals:
            return False

        auth_hash = vals.pop("hash")

        # 2. Сортируем ключи по алфавиту и склеиваем в строку key=value
        data_check_string = "\n".join([f"{k}={v}" for k, v in sorted(vals.items())])

        # 3. Вычисляем секретный ключ на основе BOT_TOKEN
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()

        # 4. Вычисляем итоговый HMAC
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        # 5. Сравниваем наш хеш с тем, что прислал Telegram
        return hmac.compare_digest(calculated_hash, auth_hash)
    except Exception:
        return False


async def get_tg_user(x_tg_init_data: str = Header(None)):
    """
    Зависимость, которая проверяет заголовок 'X-TG-Init-Data'
    """
    if not x_tg_init_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Telegram initData missing"
        )

    if not verify_telegram_data(x_tg_init_data, settings.BOT_TOKEN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Telegram signature"
        )

    return True
