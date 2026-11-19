import httpx
import pytest
from conftest import image_bytes

from app.config import Settings
from app.detector import RawDetection
from app.main import create_app


class FixedDetector:
    version = "fixed-test"

    def __init__(self, detections):
        self.detections = detections

    def warm_up(self, runs: int = 1) -> float:
        return 0.0

    def predict(self, image):
        return self.detections


async def run(settings: Settings, detections, method="detect", body=None):
    app = create_app(settings, detector_factory=lambda s, c: FixedDetector(detections))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            if method == "detect":
                return await client.post("/v1/detect", content=image_bytes(), headers={"Content-Type": "image/jpeg"})
            return await client.post("/v1/guides", json=body)


@pytest.fixture
def plastic_settings(settings):
    settings.enabled_classes = ["Plastic"]
    return settings


async def test_only_plastic_detections_are_returned(plastic_settings):
    detections = [
        RawDetection(0, 0.9, (0.1, 0.1, 0.4, 0.4)),
        RawDetection(4, 0.95, (0.6, 0.6, 0.9, 0.9)),
    ]
    body = (await run(plastic_settings, detections)).json()
    assert [d["class_name"] for d in body["detections"]] == ["Plastic"]
    assert body["model"]["enabled_classes"] == ["Plastic"]
    assert body["quality"]["status"] == "ok"


async def test_scene_without_plastic_says_so(plastic_settings):
    body = (await run(plastic_settings, [RawDetection(2, 0.9, (0.1, 0.1, 0.4, 0.4))])).json()
    assert body["detections"] == []
    assert body["quality"]["status"] == "no_detections"
    assert "plastic" in body["quality"]["message"]


async def test_hidden_class_overlap_still_marks_scan_ambiguous(plastic_settings):
    detections = [
        RawDetection(0, 0.82, (0.1, 0.1, 0.5, 0.5)),
        RawDetection(2, 0.80, (0.11, 0.1, 0.5, 0.51)),
    ]
    body = (await run(plastic_settings, detections)).json()
    assert [d["class_name"] for d in body["detections"]] == ["Plastic"]
    assert body["quality"]["status"] == "ambiguous"


async def test_guides_for_disabled_classes_are_refused(plastic_settings):
    response = await run(plastic_settings, [], method="guides", body={"class_name": "Glass", "confidence": 0.9})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "class_not_enabled"


async def test_search_style_guide_request_with_item_hint(plastic_settings):
    response = await run(
        plastic_settings,
        [],
        method="guides",
        body={"class_name": "Plastic", "confidence": 1.0, "confirmed_by_user": True, "item_hint": "yogurt cup"},
    )
    assert response.status_code == 200
    assert response.json()["guide"]["class_name"] == "Plastic"


def test_unknown_enabled_class_is_rejected(settings):
    settings.enabled_classes = ["Paper"]
    with pytest.raises(ValueError):
        create_app(settings)


async def test_model_loads_on_first_request_without_startup(settings):
    app = create_app(settings, detector_factory=lambda s, c: FixedDetector([]))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        assert (await client.get("/readyz")).status_code == 200
