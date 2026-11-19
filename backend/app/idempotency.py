"""Idempotency for retried requests.

Keys are scoped to (client, endpoint). The first request with a key runs; concurrent duplicates
wait for the same result; later duplicates within the TTL get the stored result. Reusing a key
with a different payload is rejected. Failures are not stored, so a retry runs again.

The store is in-process memory, which is correct for the single-instance deployment. Running
several replicas needs a shared store (for example Redis) behind the same interface.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .errors import ApiError

KEY_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{8,128}$")
MAX_ENTRIES = 10_000


@dataclass
class _Entry:
    fingerprint: str
    future: asyncio.Future
    expires_at: float


class IdempotencyStore:
    def __init__(self, ttl_s: float, clock: Callable[[], float] = time.monotonic):
        self._ttl_s = ttl_s
        self._clock = clock
        self._entries: dict[tuple[str, str, str], _Entry] = {}
        self._lock = asyncio.Lock()

    def _evict(self, now: float) -> None:
        expired = [k for k, e in self._entries.items() if e.future.done() and e.expires_at <= now]
        for key in expired:
            del self._entries[key]

    async def run(
        self, scope: str, endpoint: str, key: str, fingerprint: str, produce: Callable[[], Awaitable[Any]]
    ) -> tuple[Any, bool]:
        """Return (result, replayed)."""
        if not KEY_PATTERN.match(key):
            raise ApiError(400, "invalid_idempotency_key", "Idempotency-Key must be 8-128 letters, digits, - or _.")
        entry_key = (scope, endpoint, key)
        async with self._lock:
            now = self._clock()
            self._evict(now)
            entry = self._entries.get(entry_key)
            if entry is not None:
                if entry.fingerprint != fingerprint:
                    raise ApiError(
                        422, "idempotency_key_reused", "This Idempotency-Key was already used with a different request."
                    )
                owner = False
            else:
                if len(self._entries) >= MAX_ENTRIES:
                    raise ApiError(503, "overloaded", "Too many pending requests. Try again shortly.", retry_after_s=2)
                future = asyncio.get_running_loop().create_future()
                future.add_done_callback(lambda f: f.cancelled() or f.exception())
                entry = _Entry(fingerprint, future, now + self._ttl_s)
                self._entries[entry_key] = entry
                owner = True

        if not owner:
            return await asyncio.shield(entry.future), True

        try:
            result = await produce()
        except BaseException as exc:
            async with self._lock:
                self._entries.pop(entry_key, None)
            failure = exc if isinstance(exc, ApiError) else ApiError(503, "request_failed", "Request failed. Retry.")
            entry.future.set_exception(failure)
            raise
        entry.expires_at = self._clock() + self._ttl_s
        entry.future.set_result(result)
        return result, False
