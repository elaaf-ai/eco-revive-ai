"""Idempotency for retried requests.

Keys are scoped to (client, endpoint). The first request with a key runs; concurrent duplicates
wait for the same result; later duplicates within the TTL get the stored result. Reusing a key
with a different payload is rejected. Failures are not stored, so a retry runs again.

Capacity never blocks normal traffic: when the store or one client's share of it is full, the
oldest completed entries are evicted. Only a client with too many requests still in flight is
refused.

The store is in-process memory, which is correct for the single-instance deployment. Running
several replicas needs a shared store (for example Redis) behind the same interface.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .errors import ApiError

KEY_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{8,128}$")
MAX_ENTRIES = 10_000
MAX_ENTRIES_PER_CLIENT = 200

EntryKey = tuple[str, str, str]


@dataclass
class _Entry:
    fingerprint: str
    future: asyncio.Future
    expires_at: float


class IdempotencyStore:
    def __init__(
        self,
        ttl_s: float,
        clock: Callable[[], float] = time.monotonic,
        max_entries: int = MAX_ENTRIES,
        max_per_client: int = MAX_ENTRIES_PER_CLIENT,
    ):
        self._ttl_s = ttl_s
        self._clock = clock
        self._max_entries = max_entries
        self._max_per_client = max_per_client
        self._entries: OrderedDict[EntryKey, _Entry] = OrderedDict()
        self._per_client: dict[str, int] = {}
        self._lock = asyncio.Lock()

    def __len__(self) -> int:
        return len(self._entries)

    def _remove(self, key: EntryKey) -> None:
        if self._entries.pop(key, None) is not None:
            remaining = self._per_client.get(key[0], 1) - 1
            if remaining > 0:
                self._per_client[key[0]] = remaining
            else:
                self._per_client.pop(key[0], None)

    def _evict_expired(self, now: float) -> None:
        expired = [k for k, e in self._entries.items() if e.future.done() and e.expires_at <= now]
        for key in expired:
            self._remove(key)

    def _evict_oldest_done(self, scope: str | None = None) -> bool:
        """Drop the oldest completed entry (optionally for one client). Returns False if none."""
        for key, entry in self._entries.items():
            if entry.future.done() and (scope is None or key[0] == scope):
                self._remove(key)
                return True
        return False

    async def run(
        self, scope: str, endpoint: str, key: str, fingerprint: str, produce: Callable[[], Awaitable[Any]]
    ) -> tuple[Any, bool]:
        """Return (result, replayed)."""
        if not KEY_PATTERN.match(key):
            raise ApiError(400, "invalid_idempotency_key", "Idempotency-Key must be 8-128 letters, digits, - or _.")
        entry_key: EntryKey = (scope, endpoint, key)
        async with self._lock:
            now = self._clock()
            self._evict_expired(now)
            entry = self._entries.get(entry_key)
            if entry is not None:
                if entry.fingerprint != fingerprint:
                    raise ApiError(
                        422, "idempotency_key_reused", "This Idempotency-Key was already used with a different request."
                    )
                owner = False
            else:
                while self._per_client.get(scope, 0) >= self._max_per_client:
                    if not self._evict_oldest_done(scope):
                        raise ApiError(429, "too_many_pending", "Too many requests in progress. Wait a moment.",
                                       retry_after_s=2)
                while len(self._entries) >= self._max_entries:
                    if not self._evict_oldest_done():
                        raise ApiError(503, "overloaded", "Too many pending requests. Try again shortly.",
                                       retry_after_s=2)
                future = asyncio.get_running_loop().create_future()
                future.add_done_callback(lambda f: f.cancelled() or f.exception())
                entry = _Entry(fingerprint, future, now + self._ttl_s)
                self._entries[entry_key] = entry
                self._per_client[scope] = self._per_client.get(scope, 0) + 1
                owner = True

        if not owner:
            return await asyncio.shield(entry.future), True

        try:
            result = await produce()
        except BaseException as exc:
            async with self._lock:
                self._remove(entry_key)
            failure = exc if isinstance(exc, ApiError) else ApiError(503, "request_failed", "Request failed. Retry.")
            entry.future.set_exception(failure)
            raise
        entry.expires_at = self._clock() + self._ttl_s
        entry.future.set_result(result)
        return result, False
