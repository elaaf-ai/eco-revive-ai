"""Write a synthetic ONNX model with the real YOLO output layout, for tests and UI review only.

It ignores the image and always returns the same boxes. Its version string says so, and it must
never be deployed. Usage: python scripts/fixture_model.py --out models/fixture
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

CLASSES = ["Plastic", "Glass", "Metal", "Organic", "Hazardous"]
ANCHORS = 8400
FIXTURE_VERSION = "fixture-not-a-real-model"


def synthetic_output(num_classes: int = len(CLASSES)) -> np.ndarray:
    out = np.zeros((1, 4 + num_classes, ANCHORS), dtype=np.float32)
    out[0, :4, 0] = [320, 320, 200, 100]  # Plastic, high confidence
    out[0, 4 + 0, 0] = 0.9
    out[0, :4, 1] = [322, 321, 198, 102]  # duplicate that NMS removes
    out[0, 4 + 0, 1] = 0.8
    out[0, :4, 2] = [100, 250, 60, 60]  # Hazardous
    out[0, 4 + 4, 2] = 0.6
    out[0, :4, 3] = [500, 400, 50, 50]  # below threshold
    out[0, 4 + 2, 3] = 0.1
    return out


def build_model(path: Path, classes: list[str] = CLASSES) -> None:
    constant = numpy_helper.from_array(synthetic_output(len(classes)), name="const_out")
    graph = helper.make_graph(
        [helper.make_node("Identity", ["const_out"], ["output0"])],
        "synthetic_yolo",
        [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, 640, 640])],
        [helper.make_tensor_value_info("output0", TensorProto.FLOAT, [1, 4 + len(classes), ANCHORS])],
        initializer=[constant],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 9
    entry = model.metadata_props.add()
    entry.key, entry.value = "names", str(dict(enumerate(classes)))
    onnx.save(model, path)


def write_fixture(directory: Path, version: str = FIXTURE_VERSION) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    model_path = directory / "model.onnx"
    build_model(model_path)
    manifest = {
        "version": version,
        "classes": CLASSES,
        "imgsz": 640,
        "artifacts": {"onnx": {"file": "model.onnx", "sha256": hashlib.sha256(model_path.read_bytes()).hexdigest()}},
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return directory


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("models/fixture"))
    print(write_fixture(parser.parse_args().out))
