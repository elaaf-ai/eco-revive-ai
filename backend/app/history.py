"""Scan history: a small table of past scans, stored in Postgres (Neon on Vercel) or SQLite locally.

Only the result of a scan is stored: when, which model, and the class and confidence of each item.
Photos and boxes are never stored. Scans belong to the anonymous browser id the web app sends,
and only a SHA-256 hash of that id is written, so the table cannot be linked back to a browser.

The driver is pg8000 (pure Python) so nothing needs compiling on the host. Calls are synchronous
and run in a worker thread; one connection is kept per process and reopened after an error.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import ssl
import threading
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, unquote, urlparse

MAX_SCANS_PER_CLIENT = 200

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS scans (
        id TEXT PRIMARY KEY,
        client_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        model_version TEXT NOT NULL,
        quality TEXT NOT NULL,
        item_count INTEGER NOT NULL,
        top_class TEXT,
        top_confidence REAL,
        inference_ms REAL NOT NULL,
        items TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS scans_client_time ON scans (client_hash, created_at)",
)


class HistoryUnavailable(Exception):
    """The database could not be reached or answered with an error."""


@dataclass(frozen=True)
class ScanItem:
    class_name: str
    confidence: float


@dataclass(frozen=True)
class ScanRecord:
    model_version: str
    quality: str
    inference_ms: float
    items: Sequence[ScanItem]


class Connection(Protocol):
    def cursor(self) -> Any: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


def hash_client(client_id: str) -> str:
    return hashlib.sha256(f"ecorevive-history:{client_id}".encode()).hexdigest()


def now_iso(moment: datetime | None = None) -> str:
    moment = moment or datetime.now(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def describe(url: str) -> str:
    """The database kind and host, without credentials, for logs and /readyz."""
    parsed = urlparse(url)
    if parsed.scheme == "sqlite":
        return "sqlite"
    return f"postgres@{parsed.hostname or 'unknown'}"


def connect(url: str, timeout_s: float) -> tuple[Connection, str]:
    """Open a connection. Returns it with its parameter marker: "?" for SQLite, "%s" for pg8000."""
    parsed = urlparse(url)
    if parsed.scheme == "sqlite":
        # sqlite:///relative/path.db or sqlite:////absolute/path.db
        path = unquote(parsed.path[1:]) if parsed.path.startswith("/") else unquote(parsed.path)
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path or ":memory:", timeout=timeout_s, check_same_thread=False)
        return conn, "?"
    if parsed.scheme in {"postgres", "postgresql"}:
        import pg8000.dbapi  # imported here so SQLite-only setups never need it

        options = parse_qs(parsed.query)
        sslmode = options.get("sslmode", ["require"])[0]
        context = None if sslmode == "disable" else ssl.create_default_context()
        try:
            conn = pg8000.dbapi.connect(
                user=unquote(parsed.username or ""),
                password=unquote(parsed.password or ""),
                host=parsed.hostname or "localhost",
                port=parsed.port or 5432,
                database=unquote(parsed.path.lstrip("/")) or "postgres",
                ssl_context=context,
                timeout=timeout_s,
                application_name="ecorevive",
            )
        except Exception as exc:
            raise HistoryUnavailable(f"Could not connect to the database: {type(exc).__name__}") from exc
        return conn, "%s"
    raise ValueError("DATABASE_URL must start with postgres://, postgresql:// or sqlite:///")


class HistoryStore:
    """Reads and writes the scans table. Safe to call from several threads."""

    def __init__(self, url: str, timeout_s: float = 5.0) -> None:
        self.url = url
        self.kind = describe(url)
        self.timeout_s = timeout_s
        self._lock = threading.Lock()
        self._conn: Connection | None = None
        self._marker = "?"
        self._ready = False

    def _execute(self, statements: Sequence[tuple[str, Sequence[Any]]], fetch: bool = False) -> list[tuple]:
        """Run statements in one transaction, reconnecting once if the kept connection went stale."""
        with self._lock:
            for attempt in (1, 2):
                try:
                    if self._conn is None:
                        self._conn, self._marker = connect(self.url, self.timeout_s)
                    if not self._ready:
                        cursor = self._conn.cursor()
                        for ddl in SCHEMA:
                            cursor.execute(ddl)
                        self._conn.commit()
                        self._ready = True
                    cursor = self._conn.cursor()
                    rows: list[tuple] = []
                    for sql, params in statements:
                        cursor.execute(sql.replace("?", self._marker), tuple(params))
                        if fetch:
                            rows = list(cursor.fetchall())
                    self._conn.commit()
                    return rows
                except HistoryUnavailable:
                    raise
                except ValueError:
                    raise
                except Exception as exc:
                    self._reset()
                    if attempt == 2:
                        raise HistoryUnavailable(f"Database error: {type(exc).__name__}") from exc
        raise HistoryUnavailable("Database error.")  # pragma: no cover - loop always returns or raises

    def _reset(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
        self._conn = None

    def close(self) -> None:
        with self._lock:
            self._reset()

    def ping(self) -> None:
        self._execute([("SELECT 1", ())], fetch=True)

    def add(self, client_id: str, record: ScanRecord, moment: datetime | None = None) -> str:
        scan_id = uuid.uuid4().hex
        client = hash_client(client_id)
        ranked = sorted(record.items, key=lambda i: i.confidence, reverse=True)
        top = ranked[0] if ranked else None
        items = json.dumps([{"class_name": i.class_name, "confidence": round(i.confidence, 4)} for i in ranked])
        self._execute([
            (
                "INSERT INTO scans (id, client_hash, created_at, model_version, quality, item_count, top_class, "
                "top_confidence, inference_ms, items) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (scan_id, client, now_iso(moment), record.model_version, record.quality, len(ranked),
                 top.class_name if top else None, round(top.confidence, 4) if top else None,
                 round(record.inference_ms, 1), items),
            ),
            # Keep each browser's history bounded.
            (
                "DELETE FROM scans WHERE client_hash = ? AND id NOT IN "
                "(SELECT id FROM scans WHERE client_hash = ? ORDER BY created_at DESC, id DESC LIMIT ?)",
                (client, client, MAX_SCANS_PER_CLIENT),
            ),
        ])
        return scan_id

    def recent(self, client_id: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._execute([(
            "SELECT id, created_at, model_version, quality, item_count, top_class, top_confidence, inference_ms, items "
            "FROM scans WHERE client_hash = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (hash_client(client_id), limit),
        )], fetch=True)
        return [
            {
                "id": r[0], "created_at": r[1], "model_version": r[2], "quality": r[3], "item_count": int(r[4]),
                "top_class": r[5], "top_confidence": None if r[6] is None else float(r[6]),
                "inference_ms": float(r[7]), "items": json.loads(r[8]),
            }
            for r in rows
        ]

    def stats(self, client_id: str, moment: datetime | None = None) -> dict[str, Any]:
        week_ago = now_iso((moment or datetime.now(UTC)) - timedelta(days=7))
        client = hash_client(client_id)
        mine = self._execute([(
            "SELECT COUNT(*), COALESCE(SUM(item_count), 0), "
            "COALESCE(SUM(CASE WHEN created_at >= ? THEN item_count ELSE 0 END), 0) "
            "FROM scans WHERE client_hash = ?",
            (week_ago, client),
        )], fetch=True)[0]
        everyone = self._execute([(
            "SELECT COUNT(*), COALESCE(SUM(item_count), 0) FROM scans", (),
        )], fetch=True)[0]
        return {
            "you": {"scans": int(mine[0]), "items_found": int(mine[1]), "items_this_week": int(mine[2])},
            "everyone": {"scans": int(everyone[0]), "items_found": int(everyone[1])},
        }

    def clear(self, client_id: str) -> int:
        client = hash_client(client_id)
        count = self._execute([("SELECT COUNT(*) FROM scans WHERE client_hash = ?", (client,))], fetch=True)[0][0]
        self._execute([("DELETE FROM scans WHERE client_hash = ?", (client,))])
        return int(count)
