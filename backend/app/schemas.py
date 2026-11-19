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


class DetectResponse(BaseModel):
    api_version: Literal["1"] = "1"
    request_id: str
    model: ModelInfo
    image: dict[str, int]
    detections: list[Detection]
    quality: ScanQuality
    inference_ms: float


class GuideRequest(BaseModel):
    class_name: WasteClass
    confidence: float = Field(ge=0, le=1)
    confirmed_by_user: bool = False
    item_hint: str | None = Field(None, max_length=60, description="Optional user-provided item name")


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
    detail: str
