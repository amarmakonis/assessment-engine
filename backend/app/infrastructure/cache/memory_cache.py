"""
In-memory cache for lock/idempotency when Redis is disabled.
Provides set_with_nx and delete used by aggregate_pages and evaluate_question.
"""

from __future__ import annotations

import threading
from typing import Any


class MemoryCache:
    """In-memory cache implementing the subset of RedisCache used by tasks."""

    def __init__(self):
        self._store: dict[str, str] = {}
        self._lock = threading.Lock()

    def set_with_nx(self, key: str, value: str, ttl: int = 600) -> bool:
        """Set only if key doesn't exist — used for idempotency locks."""
        with self._lock:
            if key in self._store:
                return False
            self._store[key] = value
            return True

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def get(self, key: str) -> Any | None:
        with self._lock:
            return self._store.get(key)
