"""Fixtures: a synthetic ONNX model with the real YOLO output layout, and app settings.

The synthetic model ignores its input and always returns the same candidate boxes, so the
decoding, NMS, coordinate mapping and API contract can be tested without trained weights.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from fixture_model import CLASSES, build_model, write_fixture  # noqa: E402

from app.config import Settings  # noqa: E402

__all__ = ["CLASSES", "build_model", "image_bytes"]


@pytest.fixture
def model_dir(tmp_path: Path) -> Path:
    return write_fixture(tmp_path / "model", version="test-0.0.1")


@pytest.fixture
def settings(model_dir: Path) -> Settings:
    return Settings(
        model_dir=model_dir,
        static_dir=None,
        gemini_api_key=None,
        detect_per_minute=1000,
        guide_per_minute=1000,
        _env_file=None,
    )


def image_bytes(size: tuple[int, int] = (1280, 640), fmt: str = "JPEG", color=(90, 140, 200), **save) -> bytes:
    rng = np.random.default_rng(0)
    pixels = rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8)
    pixels[: size[1] // 2] = color
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, fmt, **save)
    return buffer.getvalue()
