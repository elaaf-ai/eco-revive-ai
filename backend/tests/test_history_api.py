"""Scan history through the API: saving scans, reading and clearing history, and outages."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from conftest import image_bytes
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.main import create_app

CLIENT = "browser-aaaa-1111"
OTHER = "browser-bbbb-2222"


@pytest.fixture
def client(settings, tmp_path: Path):
    settings.database_url = SecretStr(f"sqlite:///{tmp_path / 'api.db'}")
    with TestClient(create_app(settings)) as c:
        yield c


def scan(c: TestClient, save: bool, client_id: str | None = CLIENT, **headers):
    if client_id:
        headers["X-Client-Id"] = client_id
    return c.post(f"/v1/detect{'?save=true' if save else ''}", content=image_bytes(),
                  headers={"Content-Type": "image/jpeg", **headers})


def test_readyz_reports_history(client: TestClient, settings):
    assert client.get("/readyz").json()["history_enabled"] is True
    settings.database_url = None
    with TestClient(create_app(settings)) as off:
        assert off.get("/readyz").json()["history_enabled"] is False


def test_saved_scan_appears_in_history(client: TestClient):
    response = scan(client, save=True)
    assert response.status_code == 200
    body = response.json()
    assert body["scan_id"]
    history = client.get("/v1/history", headers={"X-Client-Id": CLIENT}).json()
    (saved,) = history["scans"]
    assert saved["id"] == body["scan_id"]
    assert saved["item_count"] == len(body["detections"])
    assert saved["model_version"] == "test-0.0.1"
    assert history["you"]["scans"] == 1


def test_live_frames_are_not_saved(client: TestClient):
    assert scan(client, save=False).json()["scan_id"] is None
    assert client.get("/v1/history", headers={"X-Client-Id": CLIENT}).json()["scans"] == []


def test_save_without_client_id_is_not_stored(client: TestClient):
    assert scan(client, save=True, client_id=None).json()["scan_id"] is None


def test_idempotent_retry_saves_once(client: TestClient):
    key = uuid.uuid4().hex
    first = scan(client, save=True, **{"Idempotency-Key": key}).json()
    again = scan(client, save=True, **{"Idempotency-Key": key}).json()
    assert first["scan_id"] == again["scan_id"]
    assert len(client.get("/v1/history", headers={"X-Client-Id": CLIENT}).json()["scans"]) == 1


def test_history_needs_client_id(client: TestClient):
    response = client.get("/v1/history")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "client_id_required"


def test_delete_history(client: TestClient):
    scan(client, save=True)
    scan(client, save=True, client_id=OTHER)
    deleted = client.delete("/v1/history", headers={"X-Client-Id": CLIENT})
    assert deleted.json() == {"deleted": 1}
    assert client.get("/v1/history", headers={"X-Client-Id": CLIENT}).json()["scans"] == []
    assert client.get("/v1/history", headers={"X-Client-Id": OTHER}).json()["you"]["scans"] == 1


def test_history_off_gives_503_but_scans_still_work(settings):
    with TestClient(create_app(settings)) as c:
        assert c.get("/v1/history", headers={"X-Client-Id": CLIENT}).json()["error"]["code"] == "history_disabled"
        response = scan(c, save=True)
        assert response.status_code == 200 and response.json()["scan_id"] is None


def test_database_outage_does_not_break_scanning(settings):

    settings.database_url = SecretStr("postgresql://u:p@127.0.0.1:1/db?sslmode=disable")
    settings.database_timeout_s = 1
    with TestClient(create_app(settings)) as c:
        response = scan(c, save=True)
        assert response.status_code == 200
        assert response.json()["scan_id"] is None
        outage = c.get("/v1/history", headers={"X-Client-Id": CLIENT})
        assert outage.status_code == 503
        assert outage.json()["error"]["code"] == "history_unavailable"
