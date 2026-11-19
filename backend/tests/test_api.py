import asyncio
import threading
import time

import httpx
import pytest
from conftest import image_bytes

from app.detector import RawDetection
from app.main import create_app


class SlowDetector:
    """Stands in for the model to exercise concurrency limits deterministically."""

    version = "slow-test"

    def __init__(self, delay_s: float):
        self.delay_s = delay_s
        self.calls = 0
        self._lock = threading.Lock()

    def warm_up(self, runs: int = 1) -> float:
        return 0.0

    def predict(self, image):
        with self._lock:
            self.calls += 1
        time.sleep(self.delay_s)
        return [RawDetection(1, 0.92, (0.1, 0.1, 0.5, 0.5))]


async def client_for(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
async def api(settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with await client_for(app) as client:
            yield client


def jpeg_post(client, data=None, **headers):
    return client.post("/v1/detect", content=data or image_bytes(), headers={"Content-Type": "image/jpeg", **headers})


async def test_health_and_readiness(api):
    assert (await api.get("/healthz")).json() == {"status": "ok"}
    ready = await api.get("/readyz")
    assert ready.status_code == 200
    body = ready.json()
    assert body["model_loaded"] and body["model"]["version"] == "test-0.0.1"
    assert body["guide_provider"] == "curated_only"


async def test_readiness_reports_missing_model(settings, tmp_path):
    settings.model_dir = tmp_path / "missing"
    app = create_app(settings)
    async with app.router.lifespan_context(app), await client_for(app) as client:
        ready = await client.get("/readyz")
        assert ready.status_code == 503 and ready.json()["ready"] is False
        detect = await jpeg_post(client)
        assert detect.status_code == 503
        assert detect.json()["error"]["code"] == "model_unavailable"
        assert detect.headers["Retry-After"] == "30"


async def test_detect_contract(api):
    response = await jpeg_post(api)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["api_version"] == "1"
    assert body["image"] == {"width": 1280, "height": 640}
    assert [d["class_name"] for d in body["detections"]] == ["Plastic", "Hazardous"]
    assert body["detections"][0]["confidence"] >= body["detections"][1]["confidence"]
    box = body["detections"][0]["box"]
    assert 0 <= box["x1"] < box["x2"] <= 1 and 0 <= box["y1"] < box["y2"] <= 1
    assert body["quality"]["status"] == "ok"
    assert body["model"]["status"] == "preview"
    assert response.headers["X-Request-ID"] == body["request_id"]
    assert "Content-Security-Policy" in response.headers


@pytest.mark.parametrize(
    ("data", "content_type", "status", "code"),
    [
        (b"", "image/jpeg", 400, "empty_upload"),
        (b"garbage-bytes" * 10, "image/jpeg", 415, "invalid_image"),
        (b"{}", "application/json", 415, "unsupported_media_type"),
    ],
)
async def test_detect_rejects_bad_uploads(api, data, content_type, status, code):
    response = await api.post("/v1/detect", content=data, headers={"Content-Type": content_type})
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


async def test_detect_rejects_oversized_upload(settings):
    settings.max_upload_bytes = 1000
    app = create_app(settings)
    async with app.router.lifespan_context(app), await client_for(app) as client:
        response = await jpeg_post(client)
        assert response.status_code == 413


async def test_idempotent_replay_and_key_reuse(api):
    first = await jpeg_post(api, **{"Idempotency-Key": "scan-key-0001", "X-Client-Id": "client-aaaa-1111"})
    second = await jpeg_post(api, **{"Idempotency-Key": "scan-key-0001", "X-Client-Id": "client-aaaa-1111"})
    assert first.headers["Idempotent-Replayed"] == "false"
    assert second.headers["Idempotent-Replayed"] == "true"
    assert first.json() == second.json()

    other_client = await jpeg_post(api, **{"Idempotency-Key": "scan-key-0001", "X-Client-Id": "client-bbbb-2222"})
    assert other_client.headers["Idempotent-Replayed"] == "false"

    reused = await jpeg_post(
        api, image_bytes(color=(10, 10, 10)), **{"Idempotency-Key": "scan-key-0001", "X-Client-Id": "client-aaaa-1111"}
    )
    assert reused.status_code == 422
    assert reused.json()["error"]["code"] == "idempotency_key_reused"


async def test_concurrent_duplicates_run_inference_once(settings):
    detector = SlowDetector(0.2)
    app = create_app(settings, detector_factory=lambda s, c: detector)
    async with app.router.lifespan_context(app), await client_for(app) as client:
        headers = {"Idempotency-Key": "dup-key-0001", "X-Client-Id": "client-cccc-3333"}
        responses = await asyncio.gather(*(jpeg_post(client, **headers) for _ in range(3)))
        assert all(r.status_code == 200 for r in responses)
        assert detector.calls == 1
        assert len({r.json()["request_id"] for r in responses}) == 1


async def test_failed_requests_are_not_stored(api):
    headers = {"Idempotency-Key": "fail-key-0001", "X-Client-Id": "client-dddd-4444"}
    first = await jpeg_post(api, b"bad-image-data" * 4, **headers)
    retry = await jpeg_post(api, b"bad-image-data" * 4, **headers)
    assert first.status_code == retry.status_code == 415
    assert "Idempotent-Replayed" not in retry.headers
    # The key is free again, so a corrected upload with the same key succeeds.
    assert (await jpeg_post(api, **headers)).status_code == 200


async def test_overload_returns_503_with_retry_after(settings):
    settings.inference_concurrency, settings.inference_queue_depth = 1, 0
    detector = SlowDetector(0.3)
    app = create_app(settings, detector_factory=lambda s, c: detector)
    async with app.router.lifespan_context(app), await client_for(app) as client:
        responses = await asyncio.gather(*(jpeg_post(client) for _ in range(3)))
        statuses = sorted(r.status_code for r in responses)
        assert statuses == [200, 503, 503]
        rejected = next(r for r in responses if r.status_code == 503)
        assert rejected.json()["error"]["code"] == "overloaded"
        assert rejected.headers["Retry-After"] == "1"


async def test_inference_timeout_returns_504_and_keeps_slot_until_done(settings):
    settings.inference_timeout_s, settings.inference_concurrency, settings.inference_queue_depth = 0.05, 1, 0
    detector = SlowDetector(0.3)
    app = create_app(settings, detector_factory=lambda s, c: detector)
    async with app.router.lifespan_context(app), await client_for(app) as client:
        first = await jpeg_post(client)
        assert first.status_code == 504
        # The worker is still busy, so a new request is rejected rather than oversubscribing.
        assert (await jpeg_post(client)).status_code == 503
        await asyncio.sleep(0.35)
        assert (await client.get("/v1/metrics")).json()["inference_in_flight"] == 0


async def test_rate_limit(settings):
    settings.detect_per_minute = 2
    app = create_app(settings)
    async with app.router.lifespan_context(app), await client_for(app) as client:
        codes = [(await jpeg_post(client)).status_code for _ in range(3)]
        assert codes == [200, 200, 429]


async def test_guide_endpoint_and_confirmation(api):
    ok = await api.post("/v1/guides", json={"class_name": "Glass", "confidence": 0.9})
    assert ok.status_code == 200
    guide = ok.json()["guide"]
    assert guide["source"] == "curated" and len(guide["steps"]) == 3
    assert any("chipped" in p for p in guide["precautions"])

    uncertain = await api.post("/v1/guides", json={"class_name": "Plastic", "confidence": 0.3})
    assert uncertain.status_code == 409
    assert uncertain.json()["error"]["code"] == "confirmation_required"

    confirmed = await api.post(
        "/v1/guides", json={"class_name": "Plastic", "confidence": 0.3, "confirmed_by_user": True}
    )
    assert confirmed.status_code == 200


async def test_guide_validation_error_envelope(api):
    response = await api.post("/v1/guides", json={"class_name": "Paper", "confidence": 0.9})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


async def test_openapi_documents_versioned_routes(api):
    spec = (await api.get("/openapi.json")).json()
    for path in ("/v1/detect", "/v1/guides", "/v1/model", "/healthz", "/readyz"):
        assert path in spec["paths"]
    assert "image/jpeg" in spec["paths"]["/v1/detect"]["post"]["requestBody"]["content"]
