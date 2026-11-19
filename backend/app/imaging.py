"""Upload validation by decoding, plus letterboxing and box mapping shared with the clients."""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from .errors import ApiError

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
PAD_VALUE = 114


def decode_image(data: bytes, max_pixels: int, min_side: int) -> Image.Image:
    """Decode an upload into an RGB image with EXIF rotation applied and all metadata dropped."""
    if not data:
        raise ApiError(400, "empty_upload", "The upload was empty.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            probe = Image.open(io.BytesIO(data))
            if probe.format not in ALLOWED_FORMATS:
                raise ApiError(415, "unsupported_format", "Use a JPEG, PNG or WebP image.")
            if probe.width * probe.height > max_pixels:
                raise ApiError(413, "image_too_large", "The image has too many pixels. Use a smaller photo.")
            probe.load()
            image = ImageOps.exif_transpose(probe).convert("RGB")
    except ApiError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ApiError(415, "invalid_image", "The file could not be read as an image.") from None
    if min(image.size) < min_side:
        raise ApiError(422, "image_too_small", f"The image must be at least {min_side} px on each side.")
    # A fresh image from pixel data only: no EXIF, GPS or ICC metadata survives.
    return Image.frombytes("RGB", image.size, image.tobytes())


@dataclass(frozen=True)
class Letterbox:
    scale: float
    pad_x: int
    pad_y: int
    width: int
    height: int


def letterbox(image: Image.Image, size: int) -> tuple[np.ndarray, Letterbox]:
    """Resize keeping aspect ratio and pad to size x size. Returns NCHW float32 in 0..1."""
    width, height = image.size
    scale = min(size / width, size / height)
    new_w, new_h = round(width * scale), round(height * scale)
    pad_x, pad_y = (size - new_w) // 2, (size - new_h) // 2
    canvas = Image.new("RGB", (size, size), (PAD_VALUE, PAD_VALUE, PAD_VALUE))
    canvas.paste(image.resize((new_w, new_h), Image.Resampling.BILINEAR), (pad_x, pad_y))
    tensor = np.asarray(canvas, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
    return np.ascontiguousarray(tensor), Letterbox(scale, pad_x, pad_y, width, height)


def unletterbox(boxes_xyxy: np.ndarray, lb: Letterbox) -> np.ndarray:
    """Map model-space boxes back to normalized 0..1 coordinates of the original image."""
    mapped = boxes_xyxy.astype(np.float64).copy()
    mapped[:, [0, 2]] = (mapped[:, [0, 2]] - lb.pad_x) / lb.scale / lb.width
    mapped[:, [1, 3]] = (mapped[:, [1, 3]] - lb.pad_y) / lb.scale / lb.height
    return np.clip(mapped, 0.0, 1.0)


def quality_hints(image: Image.Image) -> list[str]:
    """Cheap capture-quality hints shown to the user. They never block a scan."""
    gray = np.asarray(image.convert("L").resize((256, 256)), dtype=np.float32)
    hints = []
    mean = float(gray.mean())
    if mean < 35:
        hints.append("too_dark")
    elif mean > 225:
        hints.append("too_bright")
    sharpness = float(np.var(np.diff(gray, axis=0))) + float(np.var(np.diff(gray, axis=1)))
    if sharpness < 40:
        hints.append("blurry")
    if min(image.size) < 320:
        hints.append("small")
    return hints
