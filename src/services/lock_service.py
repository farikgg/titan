from redis.asyncio import Redis
from src.app.config import settings


class LockService:
    def __init__(self):
        self.redis = Redis.from_url(f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/2")

    async def acquire_lock(self, lock_name: str, expire: int = 600) -> bool:
        """
        Пытается установить замок. Вернет True, если успешно.
        expire: время в секундах (по дефолту 10 минут)
        """
        # NX = Set if Not Exists
        return await self.redis.set(f"lock:{lock_name}", "locked", ex=expire, nx=True)

    async def release_lock(self, lock_name: str):
        """Удалить замок вручную"""
        await self.redis.delete(f"lock:{lock_name}")

lock_service = LockService()
