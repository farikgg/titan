import hmac
import hashlib
import json
import time
from urllib.parse import parse_qsl

from fastapi import Header, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.config import settings
from src.db.initialize import get_db
from src.repositories.user_repo import UserRepository
from src.db.models.user_model import UserModel
from src.core.rbac import Role


def verify_telegram_data(init_data: str, bot_token: str) -> dict:
    vals = dict(parse_qsl(init_data))

    if "hash" not in vals:
        raise ValueError("Missing hash")

    auth_hash = vals.pop("hash")

    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(vals.items())
    )

    secret_key = hmac.new(
        b"WebAppData",
        bot_token.encode(),
        hashlib.sha256
    ).digest()

    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, auth_hash):
        raise ValueError("Invalid Telegram signature")

    # Проверка времени (24 часа)
    auth_date = vals.get("auth_date")
    if auth_date and time.time() - int(auth_date) > 86400:
        raise ValueError("Expired Telegram session")

    return vals


async def get_tg_user(
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db),
) -> UserModel:

    try:
        data = verify_telegram_data(
            x_telegram_init_data,
            settings.TELEGRAM_BOT_TOKEN,
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=f"Invalid Telegram data: {e}")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid Telegram data: {type(e).__name__}")

    if "user" not in data:
        raise HTTPException(status_code=403, detail="Telegram user missing")

    tg_user = json.loads(data["user"])
    tg_id = tg_user.get("id")

    if not tg_id:
        raise HTTPException(status_code=403, detail="Invalid Telegram user")

    repo = UserRepository(db)
    user = await repo.get_by_tg_id(tg_id)

    if not user:
        raise HTTPException(status_code=403, detail="User not registered")

    return user


def require_admin(user: UserModel = Depends(get_tg_user)):
    if user.role != Role.admin.value:
        raise HTTPException(status_code=403, detail="Нужен доступ админа")
    return user

def require_manager(user: UserModel = Depends(get_tg_user)):
    if user.role not in [
        Role.manager.value,
        Role.head_manager.value,
        Role.admin.value,
    ]:
        raise HTTPException(status_code=403, detail="Нужен доступ менеджера")
    return user
