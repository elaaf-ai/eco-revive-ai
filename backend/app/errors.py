"""Typed API errors rendered as a stable JSON envelope."""

from __future__ import annotations


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, retry_after_s: float | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retry_after_s = retry_after_s
