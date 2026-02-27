from redis.asyncio import Redis
from src.app.config import settings


class LockService:
    async def _get_redis(self):
        """
        Возвращает подключение к Redis.
        Если REDIS_URL задан (с учётом логина/пароля) — используем его.
        Иначе собираем строку подключения из REDIS_HOST/REDIS_PORT и БД №2.
        """
        if settings.REDIS_URL:
            return Redis.from_url(settings.REDIS_URL)
        return Redis.from_url(f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/2")

    async def acquire_lock(self, lock_name: str, expire: int = 600) -> bool:
        """
        Пытается установить замок. Вернет True, если успешно.
        expire: время в секундах (по дефолту 10 минут)
        """
        # NX = Set if Not Exists
        redis = await self._get_redis()
        return await redis.set(f"lock:{lock_name}", "locked", ex=expire, nx=True)

    async def release_lock(self, lock_name: str):
        """Удалить замок вручную"""
        redis = await self._get_redis()
        await redis.delete(f"lock:{lock_name}")

lock_service = LockService()
