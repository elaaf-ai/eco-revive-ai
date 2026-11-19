"""Structured JSON logs with request IDs, and in-process operational counters.

Logs never include image bytes, guide hints, API keys or client IP addresses.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import Counter, deque
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9\-]{8,64}$")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": round(record.created, 3),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        payload.update(getattr(record, "fields", {}))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").disabled = True


def log(logger: logging.Logger, msg: str, level: int = logging.INFO, **fields: object) -> None:
    logger.log(level, msg, extra={"fields": fields})


class Metrics:
    def __init__(self, window: int = 1000):
        self._lock = threading.Lock()
        self.counters: Counter[str] = Counter()
        self._latency: dict[str, deque[float]] = {}
        self._window = window
        self.started_at = time.time()

    def incr(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self.counters[name] += amount

    def observe(self, name: str, ms: float) -> None:
        with self._lock:
            self._latency.setdefault(name, deque(maxlen=self._window)).append(ms)

    def snapshot(self) -> dict:
        with self._lock:
            latency = {}
            for name, values in self._latency.items():
                ordered = sorted(values)
                latency[name] = {
                    "count": len(ordered),
                    "p50_ms": round(ordered[len(ordered) // 2], 1),
                    "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 1),
                }
            return {
                "uptime_s": round(time.time() - self.started_at),
                "counters": dict(self.counters),
                "latency": latency,
            }
