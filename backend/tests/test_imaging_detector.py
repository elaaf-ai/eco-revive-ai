import io
import json

import numpy as np
import pytest
from conftest import CLASSES, build_model, image_bytes
from PIL import Image

from app.detector import ModelLoadError, OnnxDetector, decode_yolo, nms
from app.errors import ApiError
from app.imaging import decode_image, letterbox, unletterbox


def test_decode_rejects_non_image():
    with pytest.raises(ApiError) as exc:
        decode_image(b"not an image at all", 25_000_000, 32)
    assert exc.value.status == 415


def test_decode_rejects_unsupported_format():
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64)).save(buffer, "GIF")
    with pytest.raises(ApiError) as exc:
        decode_image(buffer.getvalue(), 25_000_000, 32)
    assert exc.value.code == "unsupported_format"


def test_decode_rejects_too_many_pixels_before_loading():
    with pytest.raises(ApiError) as exc:
        decode_image(image_bytes((400, 400)), 100_000, 32)
    assert exc.value.code == "image_too_large"


def test_decode_rejects_tiny_and_truncated_images():
    with pytest.raises(ApiError) as small:
        decode_image(image_bytes((20, 20)), 25_000_000, 32)
    assert small.value.code == "image_too_small"
    with pytest.raises(ApiError) as truncated:
        decode_image(image_bytes((200, 200))[:300], 25_000_000, 32)
    assert truncated.value.status == 415


def test_decode_applies_exif_rotation_and_strips_metadata():
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 degrees clockwise
    exif[0x010F] = "SecretCam"
    data = image_bytes((300, 100), exif=exif.tobytes())
    image = decode_image(data, 25_000_000, 32)
    assert image.size == (100, 300)
    assert not image.info and not image.getexif()


def test_letterbox_round_trip_maps_to_original_coordinates():
    image = Image.new("RGB", (1280, 640))
    tensor, lb = letterbox(image, 640)
    assert tensor.shape == (1, 3, 640, 640)
    assert (lb.scale, lb.pad_x, lb.pad_y) == (0.5, 0, 160)
    # A box covering the left half of the original, in model space.
    model_box = np.array([[0, 160, 320, 480]], dtype=np.float32)
    assert np.allclose(unletterbox(model_box, lb), [[0, 0, 0.5, 1]])


def test_letterbox_portrait_padding_is_horizontal():
    _, lb = letterbox(Image.new("RGB", (480, 640)), 640)
    assert (lb.pad_x, lb.pad_y) == (80, 0)


def test_nms_keeps_highest_and_distinct_boxes():
    boxes = np.array([[0, 0, 10, 10], [1, 1, 10, 10], [50, 50, 60, 60]], dtype=np.float32)
    assert nms(boxes, np.array([0.9, 0.8, 0.7]), 0.5) == [0, 2]


def test_decode_yolo_is_class_aware_and_thresholded():
    out = np.zeros((1, 9, 4), dtype=np.float32)
    out[0, :4, 0] = [50, 50, 20, 20]
    out[0, 4, 0] = 0.9
    out[0, :4, 1] = [50, 50, 20, 20]
    out[0, 5, 1] = 0.85  # same box, different class: kept
    out[0, :4, 2] = [10, 10, 4, 4]
    out[0, 6, 2] = 0.1  # below threshold
    boxes, scores, class_ids = decode_yolo(out, 5, 0.25, 0.45, 10)
    assert class_ids.tolist() == [0, 1]
    assert np.allclose(boxes[0], [40, 40, 60, 60])


def test_decode_yolo_rejects_wrong_layout():
    with pytest.raises(ValueError):
        decode_yolo(np.zeros((1, 8, 10), dtype=np.float32), 5, 0.25, 0.45, 10)


def test_detector_end_to_end_on_synthetic_model(model_dir):
    detector = OnnxDetector(model_dir, CLASSES, 0.25, 0.45, 20)
    detections = detector.predict(Image.new("RGB", (1280, 640)))
    assert [CLASSES[d.class_id] for d in detections] == ["Plastic", "Hazardous"]
    x1, y1, x2, y2 = detections[0].box
    # cx=320, cy=320, w=200, h=100 in model space; scale 0.5, pad_y 160.
    assert np.allclose([x1, y1, x2, y2], [440 / 1280, 220 / 640, 840 / 1280, 420 / 640], atol=1e-6)
    assert detector.warm_up(1) >= 0


def test_detector_rejects_checksum_mismatch(model_dir):
    manifest = json.loads((model_dir / "manifest.json").read_text())
    manifest["artifacts"]["onnx"]["sha256"] = "0" * 64
    (model_dir / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ModelLoadError, match="checksum"):
        OnnxDetector(model_dir, CLASSES, 0.25, 0.45, 20)


def test_detector_rejects_embedded_class_mismatch(model_dir):
    four = ["Plastic", "Glass", "Metal", "Paper"]
    build_model(model_dir / "model.onnx", four + ["Hazardous"])
    import hashlib

    manifest = json.loads((model_dir / "manifest.json").read_text())
    manifest["artifacts"]["onnx"]["sha256"] = hashlib.sha256((model_dir / "model.onnx").read_bytes()).hexdigest()
    (model_dir / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ModelLoadError, match="Embedded class names"):
        OnnxDetector(model_dir, CLASSES, 0.25, 0.45, 20)


def test_detector_missing_artifact(tmp_path):
    with pytest.raises(ModelLoadError, match="missing"):
        OnnxDetector(tmp_path, CLASSES, 0.25, 0.45, 20)
