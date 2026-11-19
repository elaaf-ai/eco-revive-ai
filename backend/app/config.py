"""Runtime configuration, loaded from environment variables or a local .env file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="ECOREVIVE_", extra="ignore")

    # Model artifact. The manifest's checksum is verified before the model loads.
    model_dir: Path = REPO_ROOT / "ml" / "artifacts" / "0.1.0-preview"
    model_status: Literal["preview", "released"] = "preview"
    classes_path: Path = REPO_ROOT / "shared" / "classes.json"
    conf_threshold: float = Field(0.25, ge=0.01, le=0.99)
    iou_threshold: float = Field(0.45, ge=0.05, le=0.95)
    low_confidence: float = Field(0.5, ge=0.05, le=0.99)
    max_detections: int = Field(20, ge=1, le=100)
    onnx_threads: int = Field(2, ge=1, le=16)

    # Inference capacity. One model instance per process; requests beyond
    # concurrency + queue_depth are rejected with 503 instead of piling up.
    inference_concurrency: int = Field(1, ge=1, le=8)
    inference_queue_depth: int = Field(4, ge=0, le=64)
    inference_timeout_s: float = Field(10.0, gt=0)

    # Upload limits.
    max_upload_bytes: int = 8 * 1024 * 1024
    max_pixels: int = 25_000_000
    min_side: int = 32

    # Rate limits per client per minute.
    detect_per_minute: int = 40
    guide_per_minute: int = 20

    # Guides.
    gemini_api_key: SecretStr | None = Field(None, validation_alias="GEMINI_API_KEY")
    gemini_model: str = "gemini-3.5-flash-lite"
    guide_timeout_s: float = Field(12.0, gt=0)
    guide_retries: int = Field(1, ge=0, le=3)
    guide_cache_ttl_s: int = 3600
    guide_cache_size: int = 256

    # Idempotency for retried expensive requests. In-memory: valid for a single instance.
    idempotency_ttl_s: int = 600

    allowed_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    static_dir: Path | None = REPO_ROOT / "web" / "dist"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
