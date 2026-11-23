"""Gemini vision second opinion: the plastic verdict on scans, and item-specific guides."""

from __future__ import annotations

import base64
import io

import pytest
from conftest import image_bytes
from fastapi.testclient import TestClient
from PIL import Image

from app.guides import GeneratedGuide
from app.main import create_app
from app.vision import ItemIdentity, PhotoVerdict, VisionError, clean_item_name, crop_item


class FakeVision:
    model = "fake-vision"

    def __init__(self, photo: PhotoVerdict | Exception, item: ItemIdentity | Exception | None = None):
        self.photo, self.item = photo, item
        self.photo_calls = 0
        self.item_calls = 0

    async def check_photo(self, jpeg: bytes) -> PhotoVerdict:
        assert jpeg[:2] == b"\xff\xd8"
        self.photo_calls += 1
        if isinstance(self.photo, Exception):
            raise self.photo
        return self.photo

    async def identify_item(self, jpeg: bytes) -> ItemIdentity:
        self.item_calls += 1
        if isinstance(self.item, Exception) or self.item is None:
            raise self.item or VisionError("timeout")
        return self.item


class RecordingGuides:
    name, model = "fake", "fake-guides"

    def __init__(self):
        self.hints: list[str | None] = []

    async def generate(self, class_name: str, item_hint: str | None, variant: int = 0) -> GeneratedGuide:
        self.hints.append(item_hint)
        return GeneratedGuide(
            title=f"Reuse your {item_hint or class_name.lower()}",
            materials=["glue", "string"],
            steps=["Clean it.", "Decorate it.", "Use it."],
            precautions=["Ask an adult for help."],
        )


def app_with(settings, vision, guides=None, **overrides):
    for key, value in overrides.items():
        setattr(settings, key, value)
    return TestClient(create_app(settings, guide_provider=guides, vision_provider=vision))


def detect(c: TestClient, verify: bool = True):
    url = "/v1/detect?verify=true" if verify else "/v1/detect"
    return c.post(url, content=image_bytes(), headers={"Content-Type": "image/jpeg"})


# The fixture model's top plastic box scores 0.9, so with HIGH=0.95 the gated rule asks Gemini.
def test_gated_rule_uses_gemini_when_detector_is_unsure(settings):
    vision = FakeVision(PhotoVerdict(contains_plastic=True, plastic_items=["Glasses frame!"]))
    with app_with(settings, vision, verdict_rule="gated", verdict_yolo_high=0.95) as c:
        verdict = detect(c).json()["verdict"]
    assert vision.photo_calls == 1
    assert verdict["contains_plastic"] is True
    assert verdict["decided_by"] == "gemini"
    assert verdict["plastic_items"] == ["glasses frame"]
    assert "confirmed" in verdict["message"]


def test_gated_rule_skips_gemini_when_detector_is_sure(settings):
    vision = FakeVision(PhotoVerdict(contains_plastic=False))
    with app_with(settings, vision, verdict_rule="gated", verdict_yolo_high=0.5) as c:
        verdict = detect(c).json()["verdict"]
    assert vision.photo_calls == 0
    assert verdict == {**verdict, "contains_plastic": True, "decided_by": "detector", "gemini": "not_asked"}


def test_gemini_can_overrule_a_wrong_box(settings):
    vision = FakeVision(PhotoVerdict(contains_plastic=False))
    with app_with(settings, vision, verdict_rule="gemini") as c:
        body = detect(c).json()
    assert body["detections"], "the boxes are still returned"
    assert body["verdict"]["contains_plastic"] is False
    assert "may be wrong" in body["verdict"]["message"]


def test_live_frames_never_call_gemini(settings):
    vision = FakeVision(PhotoVerdict(contains_plastic=True))
    with app_with(settings, vision, verdict_rule="gemini") as c:
        body = detect(c, verify=False).json()
    assert body["verdict"] is None
    assert vision.photo_calls == 0


def test_gemini_outage_falls_back_to_the_detector(settings):
    vision = FakeVision(VisionError("http_503"))
    with app_with(settings, vision, verdict_rule="gated", verdict_yolo_high=0.95) as c:
        response = detect(c)
    assert response.status_code == 200
    verdict = response.json()["verdict"]
    assert verdict["gemini"] == "unavailable"
    assert verdict["decided_by"] == "detector"


def crop_b64() -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (200, 120), (200, 180, 190)).save(buffer, "JPEG")
    return base64.b64encode(buffer.getvalue()).decode()


def guide_body(**extra):
    return {"class_name": "Plastic", "confidence": 0.9, "confirmed_by_user": True, **extra}


def test_guide_is_written_for_the_identified_item(settings):
    guides = RecordingGuides()
    vision = FakeVision(PhotoVerdict(contains_plastic=True),
                        ItemIdentity(item_name="Glasses frame", material="plastic", is_plastic=True, certainty="high"))
    with app_with(settings, vision, guides) as c:
        body = c.post("/v1/guides", json=guide_body(image=crop_b64())).json()
    assert body["identified_item"] == "glasses frame"
    assert guides.hints == ["glasses frame"]
    assert body["guide"]["title"] == "Reuse your glasses frame"


def test_item_that_is_clearly_not_plastic_is_refused(settings):
    vision = FakeVision(PhotoVerdict(contains_plastic=True),
                        ItemIdentity(item_name="wine glass", material="glass", is_plastic=False, certainty="high"))
    with app_with(settings, vision, RecordingGuides()) as c:
        response = c.post("/v1/guides", json=guide_body(image=crop_b64()))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "not_this_material"
    assert "glass" in response.json()["error"]["message"]


def test_identified_hazard_gets_the_disposal_guide(settings):
    vision = FakeVision(PhotoVerdict(contains_plastic=True),
                        ItemIdentity(item_name="vape pen", material="plastic", is_plastic=True, certainty="high"))
    guides = RecordingGuides()
    with app_with(settings, vision, guides) as c:
        body = c.post("/v1/guides", json=guide_body(image=crop_b64())).json()
    assert body["guide"]["kind"] == "disposal"
    assert guides.hints == []


def test_identify_failure_still_gives_a_guide(settings):
    guides = RecordingGuides()
    with app_with(settings, FakeVision(PhotoVerdict(contains_plastic=True), VisionError("timeout")), guides) as c:
        body = c.post("/v1/guides", json=guide_body(image=crop_b64())).json()
    assert body["identified_item"] is None
    assert guides.hints == [None]


def test_bad_image_is_rejected(settings):
    with app_with(settings, FakeVision(PhotoVerdict(contains_plastic=True)), RecordingGuides()) as c:
        response = c.post("/v1/guides", json=guide_body(image="not base64!"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_image"


@pytest.mark.parametrize(("raw", "clean"), [("Glasses Frame!", "glasses frame"), ("  ", None), ("<b>bag</b>", "b bag b")])
def test_clean_item_name(raw, clean):
    assert clean_item_name(raw) == clean


def test_crop_keeps_context_and_a_minimum_size():
    image = Image.new("RGB", (1000, 800))
    crop = crop_item(image, (0.5, 0.5, 0.51, 0.51))
    assert crop.width >= 96 and crop.height >= 96


def test_gemini_rule_falls_back_to_the_detector_boxes(settings):
    with app_with(settings, FakeVision(VisionError("timeout")), verdict_rule="gemini") as c:
        verdict = detect(c).json()["verdict"]
    assert verdict["gemini"] == "unavailable"
    assert verdict["decided_by"] == "detector"
    assert verdict["contains_plastic"] is True  # the fixture model boxes plastic
