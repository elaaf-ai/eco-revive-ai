"""Versioned request and response contracts (v1). Shared by the web and Flutter clients."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class WasteClass(StrEnum):
    PLASTIC = "Plastic"
    GLASS = "Glass"
    METAL = "Metal"
    ORGANIC = "Organic"
    HAZARDOUS = "Hazardous"


class Box(BaseModel):
    """Box corners normalized to the uploaded image after EXIF rotation, in 0..1."""

    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)
    x2: float = Field(ge=0, le=1)
    y2: float = Field(ge=0, le=1)


class Detection(BaseModel):
    id: int
    class_id: int
    class_name: WasteClass
    confidence: float = Field(ge=0, le=1)
    box: Box


class ModelInfo(BaseModel):
    version: str
    status: Literal["preview", "released"]
    format: Literal["onnx"]
    classes: list[WasteClass]
    enabled_classes: list[WasteClass]


class ScanQuality(BaseModel):
    status: Literal["ok", "no_detections", "low_confidence", "ambiguous"]
    message: str
    image_hints: list[Literal["too_dark", "too_bright", "blurry", "small"]] = []


class Verdict(BaseModel):
    """Photo-level answer to "does this photo contain plastic?", from the detector and Gemini vision."""

    contains_plastic: bool
    rule: Literal["yolo", "gemini", "gated"]
    decided_by: Literal["detector", "gemini"]
    detector_score: float = Field(ge=0, le=1, description="Highest plastic confidence from the detector")
    gemini: Literal["plastic", "no_plastic", "unavailable", "not_asked"]
    plastic_items: list[str] = Field(default_factory=list, description="Item names Gemini saw")
    message: str


class DetectResponse(BaseModel):
    api_version: Literal["1"] = "1"
    request_id: str
    model: ModelInfo
    image: dict[str, int]
    detections: list[Detection]
    quality: ScanQuality
    inference_ms: float
    scan_id: str | None = Field(None, description="Set when the scan was saved to history (?save=true)")
    verdict: Verdict | None = Field(None, description="Final plastic verdict, set with ?verify=true")


class ScanItemOut(BaseModel):
    class_name: WasteClass
    confidence: float


class ScanOut(BaseModel):
    id: str
    created_at: str = Field(description="UTC, ISO 8601")
    model_version: str
    quality: Literal["ok", "no_detections", "low_confidence", "ambiguous"]
    item_count: int
    top_class: WasteClass | None
    top_confidence: float | None
    inference_ms: float
    items: list[ScanItemOut]


class ScanStats(BaseModel):
    scans: int
    items_found: int
    items_this_week: int | None = None


class HistoryResponse(BaseModel):
    api_version: Literal["1"] = "1"
    scans: list[ScanOut]
    you: ScanStats
    everyone: ScanStats


class GuideRequest(BaseModel):
    class_name: WasteClass
    confidence: float = Field(ge=0, le=1)
    confirmed_by_user: bool = False
    item_hint: str | None = Field(None, max_length=60, description="Optional user-provided item name")
    variant: int = Field(0, ge=0, le=9, description="Ask for a different idea for the same item (0 = first idea)")
    image: str | None = Field(
        None, max_length=400_000,
        description="Optional base64 JPEG crop of the selected item. Gemini names the item so the guide fits it.",
    )
    context_items: list[str] = Field(
        default_factory=list, max_length=5,
        description="Plastic items the photo check saw, used only as naming hints for the crop",
    )


class Guide(BaseModel):
    class_name: WasteClass
    kind: Literal["upcycle", "disposal"]
    title: str
    materials: list[str]
    steps: list[str] = Field(min_length=3, max_length=3)
    precautions: list[str]
    source: Literal["gemini", "curated"]
    source_detail: str
    safety_notice: str


class GuideResponse(BaseModel):
    api_version: Literal["1"] = "1"
    request_id: str
    guide: Guide
    cached: bool
    identified_item: str | None = Field(None, description="Item name Gemini read from the image, if sent")


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str
    retry_after_s: float | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class Health(BaseModel):
    status: Literal["ok"]


class Readiness(BaseModel):
    ready: bool
    model_loaded: bool
    model: ModelInfo | None
    guide_provider: Literal["gemini", "curated_only"]
    history_enabled: bool = False
    detail: str
