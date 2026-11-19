"""FastAPI application: routes only. Inference, guides and policies live in their own modules."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import API_VERSION
from .capacity import InferenceGate
from .config import Settings, get_settings
from .detector import ModelLoadError, OnnxDetector, RawDetection
from .errors import ApiError
from .guides import GeminiProvider, GuideProvider, GuideService
from .idempotency import IdempotencyStore
from .imaging import decode_image, quality_hints
from .observability import REQUEST_ID_PATTERN, Metrics, configure_logging, log, request_id_var
from .ratelimit import RateLimiter
from .schemas import (
    Box,
    Detection,
    DetectResponse,
    ErrorResponse,
    GuideRequest,
    GuideResponse,
    Health,
    ModelInfo,
    Readiness,
    ScanQuality,
    WasteClass,
)

logger = logging.getLogger("ecorevive.api")
CLIENT_ID_HEADER = "X-Client-Id"
ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (400, 409, 413, 415, 422, 429, 503, 504)
}
CSP = (
    "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; "
    "style-src 'self'; script-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'"
)


def load_classes(path: Path) -> list[str]:
    classes = json.loads(path.read_text(encoding="utf-8"))["classes"]
    return [c["name"] for c in sorted(classes, key=lambda c: c["id"])]


def iou(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def assess(
    detections: list[RawDetection],
    classes: list[str],
    low_confidence: float,
    competitors: list[RawDetection] | None = None,
    item_word: str = "waste",
) -> ScanQuality:
    """Judge the shown detections. Competitors may include hidden classes, so a plastic box that
    overlaps an equally likely metal box is still reported as ambiguous."""
    if not detections:
        return ScanQuality(
            status="no_detections",
            message=f"No {item_word} item recognised. Fill the frame with one item on a plain background.",
        )
    ranked = sorted(detections, key=lambda d: d.confidence, reverse=True)
    top = ranked[0]
    for other in sorted(competitors if competitors is not None else ranked[1:], key=lambda d: -d.confidence):
        if other is top:
            continue
        if (
            other.class_id != top.class_id
            and iou(top.box, other.box) > 0.6
            and top.confidence - other.confidence < 0.15
        ):
            return ScanQuality(
                status="ambiguous",
                message=f"This could be {classes[top.class_id]} or {classes[other.class_id]}. "
                "Retake the photo or confirm the material.",
            )
    if top.confidence < low_confidence:
        return ScanQuality(
            status="low_confidence",
            message="The scan is not sure. Retake the photo closer, in good light, or confirm the material.",
        )
    return ScanQuality(status="ok", message="Select an item to see its guide.")


def create_app(
    settings: Settings | None = None,
    detector_factory: Callable[[Settings, list[str]], OnnxDetector] | None = None,
    guide_provider: GuideProvider | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    classes = load_classes(settings.classes_path)
    unknown = set(settings.enabled_classes) - set(classes)
    if unknown or not settings.enabled_classes:
        raise ValueError(f"enabled_classes must be a non-empty subset of {classes}; unknown: {sorted(unknown)}")
    enabled = [c for c in classes if c in settings.enabled_classes]
    metrics = Metrics()

    def default_factory(s: Settings, names: list[str]) -> OnnxDetector:
        return OnnxDetector(
            s.model_dir, names, s.conf_threshold, s.iou_threshold, s.max_detections, s.onnx_threads
        )

    factory = detector_factory or default_factory
    if guide_provider is None and settings.gemini_api_key:
        guide_provider = GeminiProvider(
            settings.gemini_api_key.get_secret_value(),
            settings.gemini_model,
            settings.guide_timeout_s,
            settings.guide_retries,
        )

    model_lock = asyncio.Lock()

    async def ensure_model(app: FastAPI) -> None:
        """Load and warm the model once per process. Called at startup and, on serverless hosts
        that skip startup events, on the first request."""
        if app.state.detector is not None or app.state.model_attempted:
            return
        async with model_lock:
            if app.state.detector is not None or app.state.model_attempted:
                return
            try:
                detector = await asyncio.to_thread(factory, settings, classes)
                warm_ms = await asyncio.to_thread(detector.warm_up)
                app.state.detector = detector
                app.state.model_error = None
                log(logger, "model_ready", version=detector.version, warm_up_ms=round(warm_ms, 1))
            except (ModelLoadError, OSError, ValueError) as exc:
                app.state.model_error = str(exc)
                log(logger, "model_unavailable", logging.ERROR, reason=str(exc))
            finally:
                app.state.model_attempted = True

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await ensure_model(app)
        yield
        app.state.gate.shutdown()

    app = FastAPI(
        title="EcoRevive API",
        version=API_VERSION,
        lifespan=lifespan,
        description="Waste detection and upcycling guides. Errors use the ErrorResponse envelope.",
    )
    app.state.settings = settings
    app.state.metrics = metrics
    app.state.detector = None
    app.state.model_error = "Model is loading."
    app.state.model_attempted = False
    app.state.gate = InferenceGate(
        settings.inference_concurrency, settings.inference_queue_depth, settings.inference_timeout_s
    )
    app.state.idempotency = IdempotencyStore(settings.idempotency_ttl_s)
    app.state.limiter = RateLimiter()
    app.state.guides = GuideService(
        guide_provider, settings.low_confidence, settings.guide_cache_ttl_s, settings.guide_cache_size, metrics
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Idempotency-Key", CLIENT_ID_HEADER, "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After", "Idempotent-Replayed"],
        max_age=600,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if REQUEST_ID_PATTERN.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        elapsed = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
        if not request.url.path.startswith(("/docs", "/redoc")):
            response.headers["Content-Security-Policy"] = CSP
        if request.url.path.startswith("/v1/"):
            metrics.incr(f"http_{response.status_code}")
            token = request_id_var.set(request_id)
            log(logger, "request", method=request.method, path=request.url.path,
                status=response.status_code, duration_ms=round(elapsed, 1))
            request_id_var.reset(token)
        return response

    def error_response(status: int, code: str, message: str, retry_after: float | None = None) -> JSONResponse:
        body = {"error": {"code": code, "message": message, "request_id": request_id_var.get(),
                          "retry_after_s": retry_after}}
        headers = {"Retry-After": str(max(1, round(retry_after)))} if retry_after else None
        return JSONResponse(body, status_code=status, headers=headers)

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError):
        metrics.incr(f"error_{exc.code}")
        return error_response(exc.status, exc.code, exc.message, exc.retry_after_s)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(p) for p in first.get("loc", [])[1:])
        return error_response(422, "invalid_request", f"Invalid field {field}: {first.get('msg', 'invalid')}")

    @app.exception_handler(Exception)
    async def unexpected_error(_: Request, exc: Exception):
        log(logger, "unhandled_error", logging.ERROR, error=type(exc).__name__)
        return error_response(500, "internal_error", "Something went wrong. Try again.")

    def client_of(request: Request) -> str:
        client_id = request.headers.get(CLIENT_ID_HEADER, "")
        host = request.client.host if request.client else "unknown"
        return client_id if REQUEST_ID_PATTERN.match(client_id) else f"ip:{host}"

    def rate_key(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def model_info() -> ModelInfo:
        detector = app.state.detector
        return ModelInfo(
            version=detector.version,
            status=settings.model_status,
            format="onnx",
            classes=[WasteClass(c) for c in classes],
            enabled_classes=[WasteClass(c) for c in enabled],
        )

    @app.get("/healthz", response_model=Health, tags=["ops"])
    async def healthz():
        return Health(status="ok")

    @app.get("/readyz", response_model=Readiness, tags=["ops"], responses={503: {"model": Readiness}})
    async def readyz():
        await ensure_model(app)
        ready = app.state.detector is not None
        body = Readiness(
            ready=ready,
            model_loaded=ready,
            model=model_info() if ready else None,
            guide_provider="gemini" if app.state.guides.provider else "curated_only",
            detail="ready" if ready else app.state.model_error or "Model unavailable.",
        )
        return JSONResponse(body.model_dump(mode="json"), status_code=200 if ready else 503)

    @app.get("/v1/model", response_model=ModelInfo, tags=["detection"], responses=ERRORS)
    async def get_model():
        await ensure_model(app)
        if app.state.detector is None:
            raise ApiError(503, "model_unavailable", "The detection model is not available.", retry_after_s=30)
        return model_info()

    async def read_body(request: Request) -> bytes:
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > settings.max_upload_bytes:
            raise ApiError(413, "upload_too_large", "The image is too large. Use a photo under 8 MB.")
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > settings.max_upload_bytes:
                raise ApiError(413, "upload_too_large", "The image is too large. Use a photo under 8 MB.")
            chunks.append(chunk)
        return b"".join(chunks)

    def run_detection(data: bytes) -> tuple[list[RawDetection], dict[str, int], list[str], float]:
        image = decode_image(data, settings.max_pixels, settings.min_side)
        started = time.perf_counter()
        detections = app.state.detector.predict(image)
        elapsed = (time.perf_counter() - started) * 1000
        return detections, {"width": image.width, "height": image.height}, quality_hints(image), elapsed

    @app.post(
        "/v1/detect",
        response_model=DetectResponse,
        tags=["detection"],
        responses=ERRORS,
        openapi_extra={
            "requestBody": {
                "required": True,
                "description": "Raw image bytes. Send Idempotency-Key when retrying.",
                "content": {m: {"schema": {"type": "string", "format": "binary"}}
                            for m in ("image/jpeg", "image/png", "image/webp")},
            }
        },
    )
    async def detect(request: Request):
        app.state.limiter.check(rate_key(request), "detect", settings.detect_per_minute)
        await ensure_model(app)
        if app.state.detector is None:
            raise ApiError(503, "model_unavailable", "The detection model is not available.", retry_after_s=30)
        content_type = request.headers.get("content-type", "").split(";")[0].strip()
        if content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ApiError(415, "unsupported_media_type", "Send the image as image/jpeg, image/png or image/webp.")
        data = await read_body(request)

        async def produce() -> DetectResponse:
            detections, size, hints, elapsed = await app.state.gate.run(run_detection, data)
            metrics.observe("inference", elapsed)
            shown = [d for d in detections if classes[d.class_id] in enabled]
            item_word = enabled[0].lower() if len(enabled) == 1 else "waste"
            quality = assess(shown, classes, settings.low_confidence, competitors=detections, item_word=item_word)
            quality.image_hints = hints
            ranked = sorted(shown, key=lambda d: d.confidence, reverse=True)
            return DetectResponse(
                request_id=request_id_var.get(),
                model=model_info(),
                image=size,
                detections=[
                    Detection(
                        id=i,
                        class_id=d.class_id,
                        class_name=WasteClass(classes[d.class_id]),
                        confidence=round(d.confidence, 4),
                        box=Box(x1=d.box[0], y1=d.box[1], x2=d.box[2], y2=d.box[3]),
                    )
                    for i, d in enumerate(ranked)
                ],
                quality=quality,
                inference_ms=round(elapsed, 1),
            )

        return await idempotent(request, "detect", hashlib.sha256(data).hexdigest(), produce)

    @app.post("/v1/guides", response_model=GuideResponse, tags=["guides"], responses=ERRORS)
    async def guides(request: Request, body: GuideRequest):
        app.state.limiter.check(rate_key(request), "guides", settings.guide_per_minute)
        if body.class_name.value not in enabled:
            raise ApiError(422, "class_not_enabled", f"This app only gives guides for: {', '.join(enabled)}.")

        async def produce() -> GuideResponse:
            guide, cached = await app.state.guides.get(body)
            return GuideResponse(request_id=request_id_var.get(), guide=guide, cached=cached)

        fingerprint = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
        return await idempotent(request, "guides", fingerprint, produce)

    async def idempotent(request: Request, endpoint: str, fingerprint: str, produce) -> Response:
        key = request.headers.get("Idempotency-Key")
        if not key:
            result = await produce()
            return JSONResponse(result.model_dump(mode="json"))
        result, replayed = await app.state.idempotency.run(client_of(request), endpoint, key, fingerprint, produce)
        if replayed:
            metrics.incr(f"idempotent_replay_{endpoint}")
        return JSONResponse(result.model_dump(mode="json"), headers={"Idempotent-Replayed": str(replayed).lower()})

    @app.get("/v1/metrics", tags=["ops"])
    async def get_metrics():
        snapshot = metrics.snapshot()
        snapshot["inference_in_flight"] = app.state.gate.in_flight
        return snapshot

    static_dir = settings.static_dir
    if static_dir and (static_dir / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            candidate = (static_dir / path).resolve()
            if path and candidate.is_file() and candidate.is_relative_to(static_dir.resolve()):
                return FileResponse(candidate)
            if path.startswith(("v1/", "api/")):
                raise ApiError(404, "not_found", "Unknown API route.")
            return FileResponse(static_dir / "index.html", headers={"Cache-Control": "no-cache"})

    return app
