"""Bounded inference execution: fixed worker threads, a queue limit and per-request deadlines."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TypeVar

from .errors import ApiError

T = TypeVar("T")


class InferenceGate:
    """Admits at most concurrency + queue_depth jobs. A slot is released only when the worker
    thread actually finishes, so timed-out requests cannot oversubscribe the CPU."""

    def __init__(self, concurrency: int, queue_depth: int, timeout_s: float):
        self._executor = ThreadPoolExecutor(concurrency, thread_name_prefix="inference")
        self._capacity = concurrency + queue_depth
        self._timeout_s = timeout_s
        self._admitted = 0
        self._lock = threading.Lock()

    @property
    def in_flight(self) -> int:
        return self._admitted

    def _release(self, _: Future) -> None:
        with self._lock:
            self._admitted -= 1

    async def run(self, fn: Callable[..., T], *args: object) -> T:
        with self._lock:
            if self._admitted >= self._capacity:
                raise ApiError(503, "overloaded", "The scanner is busy. Try again in a moment.", retry_after_s=1)
            self._admitted += 1
        future = self._executor.submit(fn, *args)
        future.add_done_callback(self._release)
        try:
            return await asyncio.wait_for(asyncio.wrap_future(future), self._timeout_s)
        except TimeoutError:
            raise ApiError(504, "inference_timeout", "The scan took too long. Try again.", retry_after_s=2) from None

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
