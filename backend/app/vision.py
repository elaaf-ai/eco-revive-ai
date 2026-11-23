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

from PIL import Image, ImageDraw, ImageFont
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

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}

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


BOX_PROMPT = (
    "You check a detector's boxes for a plastic recycling app. The photo has numbered coloured rectangles; "
    "each number is written in a filled tag at the rectangle's top-left corner. Their positions are also listed "
    "below as percentages of the photo width and height (left, top, right, bottom).\n"
    "For every numbered box, look at the main object inside it and answer:\n"
    "- item_name: a short everyday name for that object, 1 to 4 words (for example \"plastic cup\", \"straw\", "
    "\"cup lid\", \"glasses frame\"). If the box mostly shows a person, face, hand, wall or background, "
    "name that (for example \"person\", \"face\", \"wall\").\n"
    "- is_plastic: true only if that object is a loose item made mainly of plastic. People, faces, hands, skin, "
    "hair, worn clothing, furniture, walls, windows and lights are false.\n"
    "- resin_code: for plastic items, the most likely resin identification code 1 to 7 (1 PET, 2 HDPE, 3 PVC, "
    "4 LDPE, 5 PP, 6 PS, 7 other or mixed) from what the object usually is made of; 0 if not plastic or you "
    "cannot tell.\n"
    "- resin_certain: true only if the recycling number is visible on the item or the object is almost always "
    "made of that plastic (for example a clear water bottle is PET).\n"
    "Return one entry per box number, in order."
)


class BoxLabel(BaseModel):
    number: int
    item_name: str
    is_plastic: bool
    resin_code: int = Field(0, ge=0, le=7)
    resin_certain: bool = False


RESIN_TYPES = {1: "PET", 2: "HDPE", 3: "PVC", 4: "LDPE", 5: "PP", 6: "PS", 7: "Other"}


class BoxLabels(BaseModel):
    boxes: list[BoxLabel]


PALETTE = [(57, 255, 20), (255, 64, 129), (0, 229, 255), (255, 214, 0), (213, 0, 249),
           (255, 109, 0), (118, 255, 3), (41, 121, 255), (255, 23, 68), (29, 233, 182)]


def draw_numbered_boxes(jpeg: bytes, boxes: list[tuple[float, float, float, float]]) -> bytes:
    """Draw each normalised box with a large numbered tag, for Gemini to refer to."""
    image = Image.open(io.BytesIO(jpeg)).convert("RGB")
    draw = ImageDraw.Draw(image)
    w, h = image.size
    size = max(16, w // 28)
    try:
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont = ImageFont.load_default(size=size)
    except TypeError:  # older Pillow
        font = ImageFont.load_default()
    for number, (x1, y1, x2, y2) in enumerate(boxes, start=1):
        colour = PALETTE[(number - 1) % len(PALETTE)]
        rect = (x1 * w, y1 * h, x2 * w, y2 * h)
        draw.rectangle(rect, outline=colour, width=max(3, w // 200))
        tag = str(number)
        tx, ty = rect[0] + 2, rect[1] + 2
        bbox = draw.textbbox((tx, ty), tag, font=font)
        draw.rectangle((bbox[0] - 4, bbox[1] - 3, bbox[2] + 4, bbox[3] + 3), fill=colour)
        draw.text((tx, ty), tag, fill=(0, 0, 0), font=font)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=88)
    return out.getvalue()


def box_list_text(boxes: list[tuple[float, float, float, float]]) -> str:
    return "\n".join(
        f"Box {n}: {round(x1 * 100)}%, {round(y1 * 100)}%, {round(x2 * 100)}%, {round(y2 * 100)}%"
        for n, (x1, y1, x2, y2) in enumerate(boxes, start=1)
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

    async def label_boxes(self, jpeg: bytes, boxes: list[tuple[float, float, float, float]]) -> BoxLabels: ...


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
        """One structured call, retried once after a dropped connection, rate limit or server error."""
        deadline = time.monotonic() + self._timeout_s
        payload = [
            {"type": "text", "text": prompt},
            {"type": "image", "data": base64.b64encode(jpeg).decode(), "mime_type": "image/jpeg"},
        ]
        for attempt in (1, 2):
            remaining = deadline - time.monotonic()
            if remaining <= 0.5:
                raise VisionError("timeout")
            try:
                reply = await asyncio.wait_for(
                    self._client.aio.interactions.create(
                        model=self.model,
                        input=payload,
                        response_format={"type": "text", "mime_type": "application/json",
                                         "schema": schema.model_json_schema()},
                        timeout=remaining,
                    ),
                    remaining,
                )
            except TimeoutError:
                raise VisionError("timeout") from None
            except Exception as exc:  # SDK and transport errors
                status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
                transient = type(exc).__name__ in {"APIConnectionError", "APITimeoutError"}
                if attempt == 1 and (transient or status in RETRYABLE_STATUS):
                    await asyncio.sleep(0.4)
                    continue
                raise VisionError(f"http_{status}" if status else type(exc).__name__) from None
            text = getattr(reply, "output_text", None)
            if not text:
                raise VisionError("empty_response")
            try:
                return schema.model_validate_json(text)
            except ValidationError:
                raise VisionError("schema") from None
        raise VisionError("exhausted")

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

    async def label_boxes(self, jpeg: bytes, boxes: list[tuple[float, float, float, float]]) -> BoxLabels:
        """Name every numbered box and say whether it is plastic, in one call."""
        prompt = f"{BOX_PROMPT}\n{box_list_text(boxes)}"
        result = await self._ask(prompt, draw_numbered_boxes(jpeg, boxes), BoxLabels)
        assert isinstance(result, BoxLabels)
        return result
