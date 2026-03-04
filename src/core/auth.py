import logging, hmac, hashlib, json, time
from urllib.parse import unquote

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
    # Логируем исходную строку для отладки (полностью)
    logger.error(f"Raw init_data FULL: {init_data}")
    
    # 1. Ручной парсинг, БЕЗ декодирования значений
    # init_data = "query_id=...&user=%7B%22id%22%3A...&hash=..."
    try:
        pairs: list[tuple[str, str]] = []
        for part in init_data.split("&"):
            if not part:
                continue
            k, _, v = part.partition("=")
            # Если ключ пустой, пропускаем
            if not k:
                continue
            pairs.append((k, v))
        parsed_data = dict(pairs)
    except Exception as e:
        logger.error(f"Parse error: {e}")
        raise ValueError("Invalid query string format")

    # Проверяем наличие hash или signature
    if "hash" not in parsed_data and "signature" not in parsed_data:
        raise ValueError("Missing hash or signature")
    
    # Telegram использует hash для проверки подписи
    # signature - это дополнительная подпись, но мы проверяем hash
    auth_hash = parsed_data.pop("hash", None)
    signature = parsed_data.pop("signature", None)
    
    if not auth_hash:
        # Если hash нет, но есть signature - это странно, но попробуем использовать signature
        if signature:
            logger.warning("Using signature instead of hash (unusual)")
            auth_hash = signature
        else:
            raise ValueError("Missing hash")

    # 2. Сортируем по ключу и собираем строку
    # Значения v остаются URL-encoded — именно так Telegram считает подпись
    sorted_pairs = sorted(parsed_data.items())
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted_pairs)

    # 3. Считаем хэш
    # По документации Telegram: 
    # secret_key = HMAC_SHA256("WebAppData", bot_token)
    # calculated_hash = HMAC_SHA256(secret_key, data_check_string)
    
    # Вариант 1: стандартный (как в документации Telegram)
    # secret_key = HMAC_SHA256("WebAppData", bot_token)
    secret_key = hmac.new(
        key=b"WebAppData",
        msg=bot_token.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()

    # calculated_hash = HMAC_SHA256(secret_key, data_check_string)
    calculated_hash = hmac.new(
        key=secret_key,
        msg=data_check_string.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    
    # Попробуем также проверить signature, если он есть
    calculated_signature = None
    if signature:
        calculated_signature = hmac.new(
            key=secret_key,
            msg=data_check_string.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        logger.error(f"Signature check: Received={signature[:20]}..., Calculated={calculated_signature[:20]}...")
    
    # ВАЖНО: Проверяем, может быть фронт использует другой бот
    # Попробуем найти токен, который подойдёт (если есть TELEGRAM_TMA_BOT_TOKEN)
    alt_token = getattr(settings, "TELEGRAM_TMA_BOT_TOKEN", None)
    if alt_token and alt_token != bot_token:
        logger.error(f"Trying alternative token: {alt_token[:30]}...")
        alt_secret_key = hmac.new(
            key=b"WebAppData",
            msg=alt_token.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        alt_calculated_hash = hmac.new(
            key=alt_secret_key,
            msg=data_check_string.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        logger.error(f"Alternative token hash: {alt_calculated_hash}")
        if hmac.compare_digest(alt_calculated_hash, auth_hash):
            logger.error("SUCCESS! Alternative token matches!")
            # Используем альтернативный токен
            secret_key = alt_secret_key
            calculated_hash = alt_calculated_hash
            bot_token = alt_token
    
    # Логируем для отладки
    logger.error(f"Secret key bytes length: {len(secret_key)}")
    logger.error(f"Data check string (first 150 chars): {data_check_string[:150]}")
    logger.error(f"Data check string bytes length: {len(data_check_string.encode('utf-8'))}")
    logger.error(f"Full data check string: {data_check_string}")

    if not hmac.compare_digest(calculated_hash, auth_hash):
        bot_id = bot_token.split(":")[0] if ":" in bot_token else "UNKNOWN"
        logger.error(f"AUTH FAIL! Token used: ...{bot_token[-5:]}")
        logger.error(f"Bot ID from token: {bot_id}")
        logger.error(f"Token full (first 30): {bot_token[:30]}...")
        logger.error(f"Received Hash: {auth_hash}")
        logger.error(f"Calculated:    {calculated_hash}")
        logger.error(f"Check String:  {data_check_string!r}")
        logger.error(f"Sorted pairs: {sorted_pairs}")
        logger.error(f"Secret key (hex, first 16): {secret_key.hex()[:32]}")
        logger.error("=" * 80)
        logger.error("ВОЗМОЖНЫЕ ПРИЧИНЫ:")
        logger.error("1. Mini App открыт у другого бота (не того, чей токен в .env)")
        logger.error(f"2. Токен в .env не соответствует боту, который открыл Mini App")
        logger.error(f"3. initData был изменён/перекодирован на фронте перед отправкой")
        logger.error("=" * 80)
        raise ValueError(
            f"Invalid Telegram signature. "
            f"Проверь: Mini App должен быть открыт у бота с ID {bot_id}. "
            f"Токен этого бота должен быть в .env как TELEGRAM_BOT_TOKEN или TELEGRAM_TMA_BOT_TOKEN."
        )

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
    # ВРЕМЕННО: для отладки можно использовать хардкод токена
    # Если в .env есть TELEGRAM_TMA_BOT_TOKEN, используем его, иначе из TELEGRAM_BOT_TOKEN
    token_to_use = getattr(settings, "TELEGRAM_TMA_BOT_TOKEN", None) or settings.TELEGRAM_BOT_TOKEN
    
    # Логируем токен для отладки (первые 20 символов)
    token_preview = token_to_use[:20] if token_to_use else "MISSING"
    logger.info(f"Using token: {token_preview}... (full: {token_to_use[:30]}...)")
    
    try:
        data = verify_telegram_data(
            x_telegram_init_data,
            token_to_use,
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
