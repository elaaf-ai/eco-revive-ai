"""Adaptive learning loop: feedback -> training data -> promotion gate."""

from __future__ import annotations

import base64
import io
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml" / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))

from app.history import FeedbackRecord, HistoryStore  # noqa: E402
from export_feedback import group_by_photo, write_feedback, yolo_line  # noqa: E402
from promote_model import decide, summarise  # noqa: E402


def photo_b64(colour=(200, 120, 40)) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (320, 240), colour).save(buffer, "JPEG")
    return base64.b64encode(buffer.getvalue()).decode()


def record(correct: bool, box, image=None, class_name="Plastic") -> FeedbackRecord:
    return FeedbackRecord(model_version="0.2.0", class_name=class_name, confidence=0.4, correct=correct,
                          box=box, item_name="plastic cup", image_b64=image)


def test_feedback_round_trip_to_yolo_dataset(tmp_path: Path):
    store = HistoryStore(f"sqlite:///{tmp_path / 'fb.db'}")
    cup_photo, face_photo = photo_b64(), photo_b64((10, 10, 10))
    store.add_feedback("browser-aaaa-1111", record(True, (0.1, 0.2, 0.5, 0.6), cup_photo))
    store.add_feedback("browser-aaaa-1111", record(False, (0.6, 0.1, 0.9, 0.4), cup_photo))
    store.add_feedback("browser-bbbb-2222", record(False, (0.2, 0.2, 0.4, 0.4), face_photo))
    store.add_feedback("browser-bbbb-2222", record(True, (0.1, 0.1, 0.2, 0.2)))  # no consent: no photo

    assert store.learning_stats() == {"feedback": 4, "correct": 2, "wrong": 2, "training_photos": 3}
    rows = store.export_feedback()
    assert len(rows) == 3 and all(r["image"] for r in rows)

    photos = group_by_photo(rows)
    assert len(photos) == 2
    counts = write_feedback(photos, tmp_path / "images", tmp_path / "labels")
    assert counts == {"photos": 2, "plastic_boxes": 1, "negative_photos": 1}
    labels = sorted(p.read_text(encoding="utf-8") for p in (tmp_path / "labels").glob("*.txt"))
    assert labels == ["", "0 0.300000 0.400000 0.400000 0.400000\n"]


def test_clearing_history_also_deletes_shared_photos(tmp_path: Path):
    store = HistoryStore(f"sqlite:///{tmp_path / 'fb.db'}")
    store.add_feedback("browser-aaaa-1111", record(True, (0.1, 0.1, 0.5, 0.5), photo_b64()))
    store.clear("browser-aaaa-1111")
    assert store.learning_stats()["feedback"] == 0


def test_yolo_line_clamps_to_the_image():
    assert yolo_line([-0.1, 0.0, 0.5, 1.2]) == "0 0.250000 0.500000 0.500000 1.000000"


def test_non_plastic_feedback_is_not_training_data():
    rows = [{"image": "x", "image_sha256": "a", "class_name": "Glass", "correct": True, "box": [0, 0, 1, 1]}]
    assert group_by_photo(rows) == {}


def report(version: str, ap50: float, balanced: float) -> dict:
    return {"model_version": version, "per_class": {"Plastic": {"ap50": ap50}},
            "photo_level": {"at_app_threshold_0.25": {"balanced_accuracy": balanced, "accuracy": 0.8}}}


def test_promotion_needs_a_real_gain_without_losing_boxes():
    current = summarise(report("0.2.0", 0.47, 0.64))
    assert decide(current, summarise(report("0.3.0", 0.48, 0.70)), 0.01, 0.02)[0] is True
    assert decide(current, summarise(report("0.3.0", 0.48, 0.645)), 0.01, 0.02)[0] is False  # gain too small
    assert decide(current, summarise(report("0.3.0", 0.40, 0.75)), 0.01, 0.02)[0] is False  # boxes got worse
