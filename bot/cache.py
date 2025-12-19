from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass
class _Entry(Generic[T]):
    value: T
    expires_at: float


class TTLCache(Generic[T]):
    def __init__(self, ttl_seconds: float, maxsize: int = 512):
        self.ttl = float(ttl_seconds)
        self.maxsize = int(maxsize)
        self._data: dict[str, _Entry[T]] = {}

    def get(self, key: str) -> T | None:
        e = self._data.get(key)
        if e is None:
            return None
        if e.expires_at < time.time():
            self._data.pop(key, None)
            return None
        return e.value

    def set(self, key: str, value: T) -> None:
        now = time.time()
        self._data[key] = _Entry(value=value, expires_at=now + self.ttl)
        self._trim(now)

    def _trim(self, now: float) -> None:
        dead = [k for k, e in self._data.items() if e.expires_at < now]
        for k in dead:
            self._data.pop(k, None)

        if len(self._data) <= self.maxsize:
            return
        items = sorted(self._data.items(), key=lambda kv: kv[1].expires_at)
        for k, _ in items[: max(0, len(self._data) - self.maxsize)]:
            self._data.pop(k, None)


def norm_query(q: str) -> str:
    q = (q or "").strip().lower()
    q = " ".join(q.split())
    return q
