"""Gemini vision checks: a second opinion on whether a photo contains plastic, and what an item is.

The YOLO detector finds where items are. Gemini then looks at the photo itself, so the app can
(1) confirm or reject "plastic" with a second, independent check, and (2) name the actual item
(for example "plastic glasses frame"), so the guide is written for that item, not a generic bottle.
The same prompt is used by ml/scripts/evaluate_hybrid.py, which measures the combined accuracy.
"""

from __future__ import annotations

import asyncio
import base64
import io
import re
import time
from typing import Literal, Protocol

from PIL import Image
from pydantic import BaseModel, Field, ValidationError

PHOTO_PROMPT = (
    "You check photos for a plastic recycling app. Look only at waste or loose household items in the photo: "
    "litter, packaging, containers, bags, bottles, caps, cups, straws, wrappers, foam, cutlery, film, small objects "
    "being held or lying on the ground or a table.\n"
    "Ignore the background: furniture, floors, walls, vehicles, clothing being worn, skin, plants and buildings.\n"
    "contains_plastic: true if at least one such item is made mainly of plastic (including plastic film, crisp "
    "packets, polystyrene foam, bottle caps and plastic frames), otherwise false. Paper, cardboard, glass, metal "
    "cans, food and cloth are not plastic.\n"
    "plastic_items: short names of the plastic items you can see, at most 5, for example "
    "\"water bottle\", \"bottle cap\", \"crisp packet\". Empty when contains_plastic is false."
)

ITEM_PROMPT = (
    "You identify one item for a plastic recycling app. The photo is a crop around the item the user selected. "
    "The selected item is inside or touches the green rectangle; the rectangle may cover only part of the item "
    "(for example one hinge of a pair of glasses), so name the whole object it belongs to. "
    "Ignore hands and background.\n"
    "item_name: a short everyday name for the item, 1 to 4 words, for example \"glasses frame\", \"shampoo bottle\", "
    "\"carrier bag\", \"yogurt cup\". Do not invent brands.\n"
    "material: its main material.\n"
    "is_plastic: true if the item is made mainly of plastic.\n"
    "certainty: high, medium or low."
)


class PhotoVerdict(BaseModel):
    contains_plastic: bool
    plastic_items: list[str] = Field(default_factory=list)


class ItemIdentity(BaseModel):
    item_name: str
    material: str
    is_plastic: bool
    certainty: Literal["high", "medium", "low"] = "medium"


class VisionError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class VisionProvider(Protocol):
    model: str

    async def check_photo(self, jpeg: bytes) -> PhotoVerdict: ...

    async def identify_item(self, jpeg: bytes, context_items: list[str] | None = None) -> ItemIdentity: ...


def to_jpeg(image: Image.Image, side: int = 768, quality: int = 85) -> bytes:
    copy = image.convert("RGB")
    copy.thumbnail((side, side))
    buffer = io.BytesIO()
    copy.save(buffer, "JPEG", quality=quality)
    return buffer.getvalue()


def crop_item(image: Image.Image, box: tuple[float, float, float, float], margin: float = 0.25) -> Image.Image:
    """Crop a normalised box with some context around it, at least 96 px on each side."""
    x1, y1, x2, y2 = box
    w, h = image.width, image.height
    bw, bh = (x2 - x1) * w, (y2 - y1) * h
    left = max(0, int(x1 * w - bw * margin))
    top = max(0, int(y1 * h - bh * margin))
    right = min(w, int(x2 * w + bw * margin))
    bottom = min(h, int(y2 * h + bh * margin))
    if right - left < 96:
        centre = (left + right) // 2
        left, right = max(0, centre - 48), min(w, centre + 48)
    if bottom - top < 96:
        centre = (top + bottom) // 2
        top, bottom = max(0, centre - 48), min(h, centre + 48)
    return image.crop((left, top, right, bottom))


def clean_item_name(name: str) -> str | None:
    cleaned = re.sub(r"[^\w \-]", " ", name, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()[:40]
    return cleaned or None


class GeminiVision:
    def __init__(self, api_key: str, model: str, timeout_s: float):
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self.model = model
        self._timeout_s = timeout_s

    async def _ask(self, prompt: str, jpeg: bytes, schema: type[BaseModel]) -> BaseModel:
        started = time.monotonic()
        try:
            reply = await asyncio.wait_for(
                self._client.aio.interactions.create(
                    model=self.model,
                    input=[
                        {"type": "text", "text": prompt},
                        {"type": "image", "data": base64.b64encode(jpeg).decode(), "mime_type": "image/jpeg"},
                    ],
                    response_format={"type": "text", "mime_type": "application/json",
                                     "schema": schema.model_json_schema()},
                    timeout=self._timeout_s,
                ),
                self._timeout_s,
            )
        except TimeoutError:
            raise VisionError("timeout") from None
        except Exception as exc:  # SDK and transport errors
            status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
            raise VisionError(f"http_{status}" if status else type(exc).__name__) from None
        text = getattr(reply, "output_text", None)
        if not text:
            raise VisionError("empty_response")
        try:
            return schema.model_validate_json(text)
        except ValidationError:
            raise VisionError("schema") from None
        finally:
            _ = time.monotonic() - started

    async def check_photo(self, jpeg: bytes) -> PhotoVerdict:
        result = await self._ask(PHOTO_PROMPT, jpeg, PhotoVerdict)
        assert isinstance(result, PhotoVerdict)
        return result

    async def identify_item(self, jpeg: bytes, context_items: list[str] | None = None) -> ItemIdentity:
        prompt = ITEM_PROMPT
        if context_items:
            seen = ", ".join(f'"{name}"' for name in context_items[:5])
            prompt += (
                f"\nA check of the whole photo saw these plastic items: {seen}. "
                "Prefer one of these names if it fits."
            )
        result = await self._ask(prompt, jpeg, ItemIdentity)
        assert isinstance(result, ItemIdentity)
        return result
