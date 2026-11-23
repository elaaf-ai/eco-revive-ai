"""Scan history store on SQLite, and on Postgres when TEST_DATABASE_URL is set.

These tests need no model, so they also run with `pytest --noconftest tests/test_history_store.py`."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import history as history_module  # noqa: E402
from app.history import (  # noqa: E402
    HistoryStore,
    HistoryUnavailable,
    ScanItem,
    ScanRecord,
    connect,
    describe,
    hash_client,
)

CLIENT = "browser-aaaa-1111"
OTHER = "browser-bbbb-2222"
PG_URL = os.environ.get("TEST_DATABASE_URL", "")


def record(*confidences: float, quality: str = "ok") -> ScanRecord:
    return ScanRecord("test-0.0.1", quality, 120.0, [ScanItem("Plastic", c) for c in confidences])


@pytest.fixture(params=["sqlite", "postgres"])
def store(request, tmp_path: Path):
    if request.param == "sqlite":
        yield HistoryStore(f"sqlite:///{tmp_path / 'history.db'}")
        return
    if not PG_URL:
        pytest.skip("TEST_DATABASE_URL is not set")
    s = HistoryStore(PG_URL)
    s.ping()
    s._execute([("DELETE FROM scans", ())])
    yield s
    s._execute([("DELETE FROM scans", ())])
    s.close()


def test_add_and_read_back_newest_first(store: HistoryStore):
    t0 = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
    first = store.add(CLIENT, record(0.4), moment=t0)
    second = store.add(CLIENT, record(0.6, 0.9), moment=t0 + timedelta(minutes=1))
    scans = store.recent(CLIENT)
    assert [s["id"] for s in scans] == [second, first]
    newest = scans[0]
    assert newest["item_count"] == 2
    assert newest["top_class"] == "Plastic"
    assert newest["top_confidence"] == pytest.approx(0.9)
    assert [i["confidence"] for i in newest["items"]] == [0.9, 0.6]
    assert newest["created_at"] == "2026-11-20T10:01:00.000Z"


def test_empty_scan_is_stored_without_top_item(store: HistoryStore):
    store.add(CLIENT, record(quality="no_detections"))
    (scan,) = store.recent(CLIENT)
    assert scan["item_count"] == 0
    assert scan["top_class"] is None and scan["top_confidence"] is None


def test_history_is_private_to_each_browser(store: HistoryStore):
    store.add(CLIENT, record(0.8))
    store.add(OTHER, record(0.7, 0.6))
    assert len(store.recent(CLIENT)) == 1
    assert len(store.recent(OTHER)) == 1
    stats = store.stats(CLIENT)
    assert stats["you"] == {"scans": 1, "items_found": 1, "items_this_week": 1}
    assert stats["everyone"] == {"scans": 2, "items_found": 3}


def test_this_week_counts_only_recent_items(store: HistoryStore):
    now = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
    store.add(CLIENT, record(0.8, 0.7), moment=now - timedelta(days=10))
    store.add(CLIENT, record(0.9), moment=now - timedelta(days=1))
    assert store.stats(CLIENT, moment=now)["you"] == {"scans": 2, "items_found": 3, "items_this_week": 1}


def test_clear_removes_only_that_browser(store: HistoryStore):
    store.add(CLIENT, record(0.8))
    store.add(CLIENT, record(0.8))
    store.add(OTHER, record(0.8))
    assert store.clear(CLIENT) == 2
    assert store.recent(CLIENT) == []
    assert len(store.recent(OTHER)) == 1


def test_history_is_capped_per_browser(store: HistoryStore, monkeypatch):
    monkeypatch.setattr(history_module, "MAX_SCANS_PER_CLIENT", 3)
    t0 = datetime(2026, 11, 20, tzinfo=UTC)
    ids = [store.add(CLIENT, record(0.5), moment=t0 + timedelta(seconds=i)) for i in range(5)]
    assert [s["id"] for s in store.recent(CLIENT, limit=10)] == ids[:1:-1]


def test_only_a_hash_of_the_browser_id_is_stored(tmp_path: Path):
    store = HistoryStore(f"sqlite:///{tmp_path / 'h.db'}")
    store.add(CLIENT, record(0.5))
    rows = store._execute([("SELECT client_hash FROM scans", ())], fetch=True)
    assert rows == [(hash_client(CLIENT),)]
    assert CLIENT not in rows[0][0]


def test_unreachable_database_raises_history_unavailable():
    store = HistoryStore("postgresql://user:pw@127.0.0.1:1/db?sslmode=disable", timeout_s=1)
    with pytest.raises(HistoryUnavailable):
        store.ping()


def test_url_handling():
    assert describe("postgresql://u:secret@ep-x.neon.tech/db") == "postgres@ep-x.neon.tech"
    assert "secret" not in describe("postgresql://u:secret@ep-x.neon.tech/db")
    with pytest.raises(ValueError):
        connect("mysql://u@h/db", 1)
