"""Regression tests for the QA bug report of 2026-11-20 (IDs B-01 ... B-25)."""

import asyncio
import json

import httpx
import pytest
from conftest import image_bytes
from pydantic import SecretStr
from test_guides import GOOD, FakeProvider, request, service

from app.errors import ApiError
from app.guides import UNSAFE_PATTERNS, GeneratedGuide, ProviderError, validate_generated
from app.idempotency import IdempotencyStore
from app.main import create_app


async def client_for(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


# ---- B-01: hazardous item names typed in the search never get an upcycling guide.
@pytest.mark.parametrize("hint", ["lithium battery", "AA batteries", "spray can", "old vape", "paint tin"])
async def test_b01_hazardous_hint_forces_disposal_guide(hint):
    provider = FakeProvider()
    guide, _ = await service(provider).get(request("Plastic", confirmed_by_user=True, item_hint=hint))
    assert guide.kind == "disposal" and guide.class_name.value == "Hazardous" and guide.source == "curated"
    assert provider.calls == 0


# ---- B-02: unsafe-content filter matches word stems.
@pytest.mark.parametrize(
    "text",
    ["Burning the edges", "Melting it down", "Soldering the joint", "Grinding it", "Smashing the bottle",
     "Puncturing the can", "use heat guns", "an acidic wash", "shattered glass"],
)
def test_b02_unsafe_stems_are_blocked(text):
    assert UNSAFE_PATTERNS.search(text)
    unsafe = GOOD.model_copy(update={"steps": [text, "Two.", "Three."]})
    with pytest.raises(ProviderError):
        validate_generated(unsafe)


def test_b02_safe_text_still_passes():
    assert validate_generated(GOOD).title == GOOD.title


# ---- B-03 / B-04: broken manifests never crash startup, and transient failures are retried.
async def test_b03_manifest_missing_key_reports_503(settings):
    manifest = settings.model_dir / "manifest.json"
    data = json.loads(manifest.read_text())
    del data["artifacts"]
    manifest.write_text(json.dumps(data))
    app = create_app(settings)
    async with app.router.lifespan_context(app), await client_for(app) as client:
        ready = await client.get("/readyz")
        assert ready.status_code == 503 and "KeyError" in ready.json()["detail"]


async def test_b04_transient_load_failure_is_retried(settings, monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "MODEL_RETRY_BASE_S", 0)
    calls = {"n": 0}

    class Ready:
        version = "retry-test"

        def warm_up(self, runs: int = 1) -> float:
            return 0.0

    def flaky(s, c):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk not ready")
        return Ready()

    app = create_app(settings, detector_factory=flaky)
    async with app.router.lifespan_context(app), await client_for(app) as client:
        assert calls["n"] == 1
        ready = await client.get("/readyz")
        assert ready.status_code == 200 and calls["n"] == 2


# ---- B-07: a full idempotency store evicts old completed entries instead of refusing everyone.
async def test_b07_store_evicts_instead_of_refusing():
    store = IdempotencyStore(ttl_s=600, max_entries=5, max_per_client=3)

    async def ok():
        return "done"

    for i in range(20):
        result, replayed = await store.run(f"client-{i % 4}", "detect", f"key-{i:08d}", "fp", ok)
        assert result == "done" and not replayed
    assert len(store) <= 5


async def test_b07_client_with_too_many_in_flight_is_limited():
    store = IdempotencyStore(ttl_s=600, max_entries=100, max_per_client=2)
    gate = asyncio.Event()

    async def slow():
        await gate.wait()
        return "done"

    tasks = [asyncio.create_task(store.run("one-client", "detect", f"key-{i:08d}", "fp", slow)) for i in range(2)]
    await asyncio.sleep(0)
    with pytest.raises(ApiError) as exc:
        await store.run("one-client", "detect", "key-99999999", "fp", slow)
    assert exc.value.status == 429
    gate.set()
    await asyncio.gather(*tasks)


# ---- B-08: forwarded headers are ignored unless the host's proxy header is configured.
async def test_b08_spoofed_forwarded_for_does_not_bypass_rate_limit(settings):
    settings.detect_per_minute = 2
    app = create_app(settings)
    async with app.router.lifespan_context(app), await client_for(app) as client:
        codes = []
        for i in range(3):
            response = await client.post("/v1/detect", content=image_bytes(),
                                         headers={"Content-Type": "image/jpeg", "X-Forwarded-For": f"10.0.0.{i}"})
            codes.append(response.status_code)
        assert codes == [200, 200, 429]


async def test_b08_configured_proxy_header_is_used(settings):
    settings.detect_per_minute = 1
    settings.client_ip_header = "x-forwarded-for"
    app = create_app(settings)
    async with app.router.lifespan_context(app), await client_for(app) as client:
        for ip in ("1.1.1.1", "2.2.2.2"):
            response = await client.post("/v1/detect", content=image_bytes(),
                                         headers={"Content-Type": "image/jpeg", "X-Forwarded-For": ip})
            assert response.status_code == 200


# ---- B-10 / B-25: bad and unknown static paths are 404 with full headers; 500s keep a request id.
async def test_b10_b25_static_paths(settings, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<title>EcoRevive</title>")
    settings.static_dir = dist
    app = create_app(settings)
    async with app.router.lifespan_context(app), await client_for(app) as client:
        null_byte = await client.get("/%00")
        assert null_byte.status_code == 404 and null_byte.headers.get("X-Request-ID")
        assert null_byte.json()["error"]["request_id"] == null_byte.headers["X-Request-ID"]
        assert (await client.get("/nonexistent.js")).status_code == 404
        assert (await client.get("/scan")).status_code == 200  # app routes still serve the page


async def test_b10_unhandled_error_keeps_request_id_and_headers(settings):
    app = create_app(settings)

    @app.get("/v1/boom")
    async def boom():
        raise RuntimeError("boom")

    async with app.router.lifespan_context(app), await client_for(app) as client:
        response = await client.get("/v1/boom")
        assert response.status_code == 500
        assert response.headers.get("X-Request-ID") == response.json()["error"]["request_id"] != "-"
        assert response.headers.get("X-Content-Type-Options") == "nosniff"


# ---- B-11 / B-12: "another idea" varies; non-matching and empty hints are refused.
async def test_b11_variant_requests_a_new_idea():
    provider = FakeProvider()
    svc = service(provider)
    await svc.get(request("Plastic", item_hint="bottle"))
    await svc.get(request("Plastic", item_hint="bottle", variant=1))
    assert provider.calls == 2 and provider.last_variant == 1


async def test_b12_not_this_material_is_refused():
    wrong = GOOD.model_copy(update={"matches_category": False})
    with pytest.raises(ApiError) as exc:
        await service(FakeProvider(result=wrong)).get(request("Plastic", item_hint="banana peel"))
    assert exc.value.code == "not_this_material"


async def test_b12_empty_hint_is_refused():
    with pytest.raises(ApiError) as exc:
        await service(FakeProvider()).get(request("Plastic", item_hint="#"))
    assert exc.value.code == "invalid_item_hint"


def test_b12_generated_guide_keeps_material_flag():
    guide = GeneratedGuide(**{**GOOD.model_dump(), "matches_category": False})
    assert validate_generated(guide).matches_category is False


# ---- B-13: fonts inlined as data: URIs are allowed by the CSP.
async def test_b13_csp_allows_data_fonts(settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app), await client_for(app) as client:
        assert "font-src 'self' data:" in (await client.get("/healthz")).headers["Content-Security-Policy"]


# ---- B-14: media types are case-insensitive.
async def test_b14_uppercase_content_type(settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app), await client_for(app) as client:
        response = await client.post("/v1/detect", content=image_bytes(), headers={"Content-Type": "image/JPEG"})
        assert response.status_code == 200


# ---- B-19: a blank query lists every item.
async def test_b19_blank_query_lists_everything(settings):
    app = create_app(settings)
    async with await client_for(app) as client:
        assert len((await client.get("/v1/items", params={"q": " "})).json()["items"]) == 14


# ---- B-23: a replay carries the original request id in both body and header.
async def test_b23_replay_request_id_is_consistent(settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app), await client_for(app) as client:
        headers = {"Content-Type": "image/jpeg", "Idempotency-Key": "replay-key-01", "X-Client-Id": "client-replay-1"}
        await client.post("/v1/detect", content=image_bytes(), headers=headers)
        replay = await client.post("/v1/detect", content=image_bytes(), headers=headers)
        assert replay.headers["Idempotent-Replayed"] == "true"
        assert replay.headers["X-Request-ID"] == replay.json()["request_id"]


# ---- B-24: metrics are hidden without a token and need the right one when configured.
async def test_b24_metrics_require_token(settings):
    app = create_app(settings)
    async with await client_for(app) as client:
        assert (await client.get("/v1/metrics")).status_code == 404
    settings.metrics_token = SecretStr("right-token-123")
    app = create_app(settings)
    async with await client_for(app) as client:
        assert (await client.get("/v1/metrics", headers={"Authorization": "Bearer wrong"})).status_code == 404
        ok = await client.get("/v1/metrics", headers={"Authorization": "Bearer right-token-123"})
        assert ok.status_code == 200 and "counters" in ok.json()
