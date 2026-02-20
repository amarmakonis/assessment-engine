"""
Redis cache layer with typed helpers.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.config import get_settings
from app.extensions import get_redis

logger = logging.getLogger(__name__)


class RedisCache:
    def __init__(self):
        self._ttl = get_settings().REDIS_CACHE_TTL

    @property
    def _client(self):
        return get_redis()

    def get(self, key: str) -> Any | None:
        raw = self._client.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        serialized = json.dumps(value) if not isinstance(value, str) else value
        self._client.setex(key, ttl or self._ttl, serialized)

    def delete(self, key: str) -> None:
        self._client.delete(key)

    def exists(self, key: str) -> bool:
        return bool(self._client.exists(key))

    def increment(self, key: str, amount: int = 1) -> int:
        return self._client.incr(key, amount)

    def set_with_nx(self, key: str, value: str, ttl: int) -> bool:
        """Set only if key doesn't exist — used for idempotency locks."""
        return bool(self._client.set(key, value, nx=True, ex=ttl))
