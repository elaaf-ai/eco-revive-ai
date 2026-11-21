"""Regression tests for the QA bug report of 2026-11-20 (ML script items B-26, B-27)."""

import subprocess
import sys
import types
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[2]


def load_export_module():
    # export_model imports ultralytics at module level; parity logic itself does not need it.
    sys.modules.setdefault("ultralytics", types.SimpleNamespace(YOLO=None))
    sys.path.insert(0, str(ROOT / "ml" / "scripts"))
    import export_model

    return export_model


def test_b27_parity_counts_extra_candidate_detections():
    export_model = load_export_module()
    box = np.array([10, 10, 50, 50], dtype=float)
    reference = [(0, 0.9, box)]
    candidate = [(0, 0.9, box), (0, 0.8, np.array([200, 200, 260, 260], dtype=float))]
    matched, _ = export_model.match_counts(reference, candidate)
    back, _ = export_model.match_counts(candidate, reference)
    assert matched == 1 and back == 1  # one extra candidate box is not explained by the reference


def write_dataset(root: Path, names) -> Path:
    for split in ("train", "val", "test"):
        (root / "images" / split).mkdir(parents=True)
        (root / "labels" / split).mkdir(parents=True)
        from PIL import Image

        Image.new("RGB", (32, 32), (10 * len(split), 0, 0)).save(root / "images" / split / f"{split}.jpg")
        (root / "labels" / split / f"{split}.txt").write_text("0 0.5 0.5 0.2 0.2\n")
    data = root / "data.yaml"
    data.write_text(yaml.safe_dump({"path": str(root), "train": "images/train", "val": "images/val",
                                    "test": "images/test", "names": names}))
    return data


def test_b26_validate_dataset_accepts_list_names(tmp_path):
    data = write_dataset(tmp_path, ["Plastic", "Glass", "Metal", "Organic", "Hazardous"])
    result = subprocess.run([sys.executable, str(ROOT / "ml/scripts/validate_dataset.py"), "--data", str(data)],
                            capture_output=True, text=True)
    assert "differ from canonical" not in result.stdout
    assert "Traceback" not in result.stderr


def test_b26_evaluate_onnx_reports_empty_split_clearly(tmp_path):
    data = write_dataset(tmp_path, {0: "Plastic", 1: "Glass", 2: "Metal", 3: "Organic", 4: "Hazardous"})
    for image in (tmp_path / "images" / "val").glob("*.jpg"):
        image.unlink()
    backend_python = ROOT / "backend" / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    python = str(backend_python) if backend_python.exists() else sys.executable
    result = subprocess.run([python, str(ROOT / "ml/scripts/evaluate_onnx.py"), "--model-dir", str(tmp_path),
                             "--data", str(data), "--split", "val"], capture_output=True, text=True)
    assert result.returncode != 0
    assert "No .jpg images found" in result.stderr or "No module named" in result.stderr
    assert "ZeroDivisionError" not in result.stderr and "IndexError" not in result.stderr
