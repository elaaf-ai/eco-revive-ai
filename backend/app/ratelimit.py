"""Sliding-window rate limiting per client, in process memory (single instance)."""

from __future__ import annotations

import time
from collections import OrderedDict, deque
from collections.abc import Callable

from .errors import ApiError

MAX_CLIENTS = 50_000


class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._windows: OrderedDict[tuple[str, str], deque[float]] = OrderedDict()

    def check(self, client: str, bucket: str, per_minute: int) -> None:
        now = self._clock()
        key = (client, bucket)
        window = self._windows.pop(key, None) or deque()
        while window and window[0] <= now - 60:
            window.popleft()
        if len(window) >= per_minute:
            self._windows[key] = window
            retry = max(1.0, 60 - (now - window[0]))
            raise ApiError(429, "rate_limited", "Too many requests. Wait a moment and try again.", retry_after_s=retry)
        window.append(now)
        self._windows[key] = window
        while len(self._windows) > MAX_CLIENTS:
            self._windows.popitem(last=False)
