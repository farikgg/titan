import logging, hmac, hashlib, json, time, unquote
from urllib.parse import parse_qsl

from fastapi import Header, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.config import settings
from src.db.initialize import get_db
from src.repositories.user_repo import UserRepository
from src.db.models.user_model import UserModel
from src.core.rbac import Role

logger = logging.getLogger(__name__)


def verify_telegram_data(init_data: str, bot_token: str) -> dict:
    """
    Валидация initData для Telegram WebApp.

    ВАЖНО: Telegram подписывает значения в том виде, в котором они пришли
    в query string (URL-encoded), отсортированные по ключу.
    """
    # 1. Ручной парсинг, БЕЗ декодирования значений
    # init_data = "query_id=...&user=%7B%22id%22%3A...&hash=..."
    try:
        pairs: list[tuple[str, str]] = []
        for part in init_data.split("&"):
            if not part:
                continue
            k, _, v = part.partition("=")
            pairs.append((k, v))
        parsed_data = dict(pairs)
    except Exception:
        raise ValueError("Invalid query string format")

    if "hash" not in parsed_data:
        raise ValueError("Missing hash")

    auth_hash = parsed_data.pop("hash")
    # На всякий случай убираем signature, если Telegram её пришлёт
    parsed_data.pop("signature", None)

    # 2. Сортируем по ключу и собираем строку
    # Значения v остаются URL-encoded — именно так Telegram считает подпись
    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(parsed_data.items())
    )

    # 3. Считаем хэш
    secret_key = hmac.new(
        key=b"WebAppData",
        msg=bot_token.encode(),
        digestmod=hashlib.sha256,
    ).digest()

    calculated_hash = hmac.new(
        key=secret_key,
        msg=data_check_string.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, auth_hash):
        logger.error(f"AUTH FAIL! Token used: ...{bot_token[-5:]}")
        logger.error(f"Received Hash: {auth_hash}")
        logger.error(f"Calculated:    {calculated_hash}")
        logger.error(f"Check String:  {data_check_string!r}")
        raise ValueError("Invalid Telegram signature")

    # 4. После успешной проверки можно декодировать значения
    decoded_data: dict[str, str] = {}
    for k, v in parsed_data.items():
        decoded_data[k] = unquote(v)

    auth_date = decoded_data.get("auth_date")
    if auth_date and time.time() - int(auth_date) > 86400:
        raise ValueError("Expired Telegram session")

    return decoded_data


async def get_tg_user(
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db),
) -> UserModel:
    try:
        # ИСПОЛЬЗУЕМ ТОКЕН ИЗ .env, БЕЗ ХАРДКОДА
        data = verify_telegram_data(
            x_telegram_init_data,
            settings.TELEGRAM_BOT_TOKEN,
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=f"Invalid Telegram data: {e}")
    except Exception as e:
        logger.error(f"Auth error: {e}")
        raise HTTPException(status_code=401, detail="Auth error")

    if "user" not in data:
        raise HTTPException(status_code=403, detail="Telegram user missing")

    try:
        tg_user = json.loads(data["user"])
    except json.JSONDecodeError:
        raise HTTPException(status_code=403, detail="Invalid user JSON")

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
