"""
нам нужно защитить backend, чтобы только TMA мог запрашивать цены
"""
import hmac, hashlib, json

from fastapi import Header, HTTPException
from urllib.parse import parse_qsl

from src.app.config import settings
from src.repositories.user_repo import UserRepository


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
    if not x_tg_init_data:
        raise HTTPException(status_code=401, detail="Telegram initData missing")

    if not verify_telegram_data(x_tg_init_data, settings.BOT_TOKEN):
        raise HTTPException(status_code=403, detail="Invalid Telegram signature")

    data = dict(parse_qsl(x_tg_init_data))

    if "user" not in data:
        raise HTTPException(status_code=403, detail="Telegram user missing")

    tg_user = json.loads(data["user"])
    tg_id = tg_user.get("id")

    if not tg_id:
        raise HTTPException(status_code=403, detail="Invalid Telegram user")

    user = await UserRepository.get_by_tg_id(tg_id)
    if not user:
        raise HTTPException(status_code=403, detail="User not registered")

    return user
