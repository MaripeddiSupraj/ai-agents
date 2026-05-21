from typing import Optional
import redis.asyncio as redis
from app.models.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class RedisClient:
    _instance: Optional["RedisClient"] = None

    def __init__(self) -> None:
        settings = get_settings()
        self._client: Optional[redis.Redis] = None
        self._redis_url = settings.redis_url
        self._ttl = settings.redis_ttl

    @classmethod
    def get_instance(cls) -> "RedisClient":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def connect(self) -> None:
        if self._client is None:
            try:
                self._client = redis.from_url(
                    self._redis_url,
                    decode_responses=True,
                    socket_connect_timeout=5,
                )
                await self._client.ping()
                logger.info("redis_connected", url=self._redis_url)
            except Exception as e:
                logger.warning("redis_connection_failed", error=str(e))
                self._client = None

    async def disconnect(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None

    async def set_state(self, key: str, value: str) -> bool:
        if not self._client:
            return False
        try:
            await self._client.setex(key, self._ttl, value)
            return True
        except Exception as e:
            logger.warning("redis_set_failed", key=key, error=str(e))
            return False

    async def get_state(self, key: str) -> Optional[str]:
        if not self._client:
            return None
        try:
            return await self._client.get(key)
        except Exception as e:
            logger.warning("redis_get_failed", key=key, error=str(e))
            return None

    async def delete_state(self, key: str) -> bool:
        if not self._client:
            return False
        try:
            await self._client.delete(key)
            return True
        except Exception as e:
            logger.warning("redis_delete_failed", key=key, error=str(e))
            return False

    @property
    def is_connected(self) -> bool:
        return self._client is not None
