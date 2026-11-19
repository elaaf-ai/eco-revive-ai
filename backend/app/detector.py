"""ONNX Runtime detector for Ultralytics YOLO exports with output shape [1, 4 + classes, anchors]."""

from __future__ import annotations

import ast
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image

from .imaging import letterbox, unletterbox


class ModelLoadError(RuntimeError):
    pass


@dataclass(frozen=True)
class RawDetection:
    class_id: int
    confidence: float
    box: tuple[float, float, float, float]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
    """Greedy non-maximum suppression. boxes are xyxy."""
    order = scores.argsort()[::-1]
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    keep: list[int] = []
    while order.size:
        i = int(order[0])
        keep.append(i)
        xx1 = np.maximum(boxes[i, 0], boxes[order[1:], 0])
        yy1 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
        xx2 = np.minimum(boxes[i, 2], boxes[order[1:], 2])
        yy2 = np.minimum(boxes[i, 3], boxes[order[1:], 3])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)
        order = order[1:][iou <= iou_threshold]
    return keep


def decode_yolo(
    output: np.ndarray, num_classes: int, conf_threshold: float, iou_threshold: float, max_detections: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Decode [1, 4 + C, N] into xyxy boxes, scores and class ids with class-aware NMS."""
    if output.ndim != 3 or output.shape[1] != 4 + num_classes:
        raise ValueError(f"Unexpected output shape {output.shape} for {num_classes} classes")
    predictions = output[0].T
    class_scores = predictions[:, 4:]
    class_ids = class_scores.argmax(axis=1)
    scores = class_scores[np.arange(len(class_ids)), class_ids]
    mask = scores >= conf_threshold
    if not mask.any():
        empty = np.zeros((0,), dtype=np.float32)
        return np.zeros((0, 4), dtype=np.float32), empty, empty.astype(np.int64)
    cx, cy, w, h = predictions[mask, :4].T
    boxes = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1)
    scores, class_ids = scores[mask], class_ids[mask]
    # Offset boxes per class so NMS never suppresses across classes.
    offset = class_ids[:, None].astype(np.float32) * 10_000.0
    keep = nms(boxes + offset, scores, iou_threshold)[:max_detections]
    return boxes[keep], scores[keep], class_ids[keep]


class OnnxDetector:
    def __init__(
        self,
        model_dir: Path,
        expected_classes: list[str],
        conf_threshold: float,
        iou_threshold: float,
        max_detections: int,
        threads: int = 2,
    ):
        manifest_path = model_dir / "manifest.json"
        model_path = model_dir / "model.onnx"
        if not manifest_path.is_file() or not model_path.is_file():
            raise ModelLoadError(f"Model artifact missing in {model_dir}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_sha = manifest["artifacts"]["onnx"]["sha256"]
        if sha256_file(model_path) != expected_sha:
            raise ModelLoadError("model.onnx checksum does not match manifest.json")
        if manifest["classes"] != expected_classes:
            raise ModelLoadError(f"Manifest classes {manifest['classes']} differ from {expected_classes}")

        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(model_path), options, providers=["CPUExecutionProvider"])
        embedded = self.session.get_modelmeta().custom_metadata_map.get("names")
        if embedded:
            names = ast.literal_eval(embedded)
            if [names[i] for i in sorted(names)] != expected_classes:
                raise ModelLoadError(f"Embedded class names {names} differ from {expected_classes}")

        model_input = self.session.get_inputs()[0]
        self.input_name = model_input.name
        self.imgsz = int(model_input.shape[2]) if isinstance(model_input.shape[2], int) else int(manifest["imgsz"])
        self.version = manifest["version"]
        self.classes = expected_classes
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self.max_detections = max_detections

    def warm_up(self, runs: int = 2) -> float:
        """Run dummy inferences so the first user request does not pay initialization cost."""
        image = Image.new("RGB", (self.imgsz, self.imgsz), (114, 114, 114))
        start = time.perf_counter()
        for _ in range(runs):
            self.predict(image)
        return (time.perf_counter() - start) * 1000 / runs

    def predict(self, image: Image.Image) -> list[RawDetection]:
        tensor, lb = letterbox(image, self.imgsz)
        output = self.session.run(None, {self.input_name: tensor})[0]
        boxes, scores, class_ids = decode_yolo(
            output, len(self.classes), self.conf_threshold, self.iou_threshold, self.max_detections
        )
        mapped = unletterbox(boxes, lb)
        return [
            RawDetection(int(c), float(s), (float(box[0]), float(box[1]), float(box[2]), float(box[3])))
            for box, s, c in zip(mapped, scores, class_ids, strict=True)
            if box[2] - box[0] > 1e-3 and box[3] - box[1] > 1e-3
        ]
