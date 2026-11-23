"""FastAPI application: routes only. Inference, guides and policies live in their own modules."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import API_VERSION
from .capacity import InferenceGate
from .catalog import Catalog, CatalogItem, CatalogSummary
from .config import Settings, get_settings
from .curated_guides import SAFETY_NOTICE
from .detector import ModelLoadError, OnnxDetector, RawDetection
from .errors import ApiError
from .guides import GeminiProvider, GuideProvider, GuideService
from .history import HistoryStore, HistoryUnavailable, ScanItem, ScanRecord
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
    HistoryResponse,
    ModelInfo,
    Readiness,
    ScanQuality,
    Verdict,
    WasteClass,
)
from .vision import GeminiVision, VisionError, VisionProvider, clean_item_name, to_jpeg

logger = logging.getLogger("ecorevive.api")
CLIENT_ID_HEADER = "X-Client-Id"
MODEL_RETRY_BASE_S = 5
MODEL_RETRY_MAX_S = 300
ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (400, 409, 413, 415, 422, 429, 503, 504)
}
CSP = (
    "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; "
    "style-src 'self'; script-src 'self'; font-src 'self' data:; frame-ancestors 'none'; base-uri 'self'"
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
    vision_provider: VisionProvider | None = None,
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

    if vision_provider is None and settings.gemini_api_key and settings.vision_enabled:
        vision_provider = GeminiVision(
            settings.gemini_api_key.get_secret_value(), settings.gemini_model, settings.vision_timeout_s
        )

    model_lock = asyncio.Lock()

    async def ensure_model(app: FastAPI) -> None:
        """Load and warm the model once per process. Called at startup and, on serverless hosts
        that skip startup events, on the first request."""
        if app.state.detector is not None or time.monotonic() < app.state.model_retry_at:
            return
        async with model_lock:
            if app.state.detector is not None or time.monotonic() < app.state.model_retry_at:
                return
            try:
                detector = await asyncio.to_thread(factory, settings, classes)
                warm_ms = await asyncio.to_thread(detector.warm_up)
                app.state.detector = detector
                app.state.model_error = None
                log(logger, "model_ready", version=detector.version, warm_up_ms=round(warm_ms, 1))
            except Exception as exc:  # any bad artifact or manifest: report 503, never crash startup
                app.state.model_failures += 1
                backoff = min(MODEL_RETRY_MAX_S, MODEL_RETRY_BASE_S * 2 ** (app.state.model_failures - 1))
                app.state.model_retry_at = time.monotonic() + backoff
                reason = str(exc) if isinstance(exc, ModelLoadError) else f"{type(exc).__name__}: {exc}"
                app.state.model_error = reason
                log(logger, "model_unavailable", logging.ERROR, reason=reason, retry_in_s=backoff)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await ensure_model(app)
        if app.state.history is not None:
            try:
                await asyncio.to_thread(app.state.history.ping)
                log(logger, "history_ready", database=app.state.history.kind)
            except HistoryUnavailable as exc:  # scanning still works; history calls report 503
                log(logger, "history_unavailable", logging.WARNING, reason=str(exc))
        yield
        app.state.gate.shutdown()
        if app.state.history is not None:
            app.state.history.close()

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
    app.state.model_failures = 0
    app.state.model_retry_at = 0.0
    app.state.gate = InferenceGate(
        settings.inference_concurrency, settings.inference_queue_depth, settings.inference_timeout_s
    )
    app.state.idempotency = IdempotencyStore(settings.idempotency_ttl_s)
    app.state.limiter = RateLimiter()
    app.state.vision = vision_provider
    app.state.history = (
        HistoryStore(settings.database_url.get_secret_value(), settings.database_timeout_s)
        if settings.database_url and settings.database_url.get_secret_value().strip()
        else None
    )
    app.state.guides = GuideService(
        guide_provider, settings.low_confidence, settings.guide_cache_ttl_s, settings.guide_cache_size, metrics
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST", "DELETE"],
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
            try:
                response = await call_next(request)
            except Exception as exc:
                log(logger, "unhandled_error", logging.ERROR, error=type(exc).__name__, path=request.url.path)
                response = error_response(500, "internal_error", "Something went wrong. Try again.")
        finally:
            request_id_var.reset(token)
        elapsed = (time.perf_counter() - started) * 1000
        if "x-request-id" not in response.headers:
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
        if settings.client_ip_header:
            forwarded = request.headers.get(settings.client_ip_header, "").split(",")[0].strip()
            if forwarded:
                return forwarded
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
            history_enabled=app.state.history is not None,
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

    def run_detection(
        data: bytes, want_jpeg: bool = False
    ) -> tuple[list[RawDetection], dict[str, int], list[str], float, bytes | None]:
        image = decode_image(data, settings.max_pixels, settings.min_side)
        started = time.perf_counter()
        detections = app.state.detector.predict(image)
        elapsed = (time.perf_counter() - started) * 1000
        jpeg = to_jpeg(image) if want_jpeg else None
        return detections, {"width": image.width, "height": image.height}, quality_hints(image), elapsed, jpeg

    async def decide(shown: list[RawDetection], jpeg: bytes | None) -> Verdict:
        """Final "contains plastic?" answer. The rule and thresholds were chosen on the validation split."""
        score = max((d.confidence for d in shown), default=0.0)
        rule = settings.verdict_rule
        detector_sure = score >= settings.verdict_yolo_high or score < settings.verdict_yolo_low
        needs_gemini = rule == "gemini" or (rule == "gated" and not detector_sure)
        gemini = "not_asked"
        items: list[str] = []
        gemini_says: bool | None = None
        if needs_gemini and jpeg is not None and app.state.vision is not None:
            try:
                answer = await app.state.vision.check_photo(jpeg)
                gemini_says = answer.contains_plastic
                gemini = "plastic" if gemini_says else "no_plastic"
                items = [n for n in (clean_item_name(i) for i in answer.plastic_items[:5]) if n]
                metrics.incr(f"vision_{gemini}")
            except VisionError as exc:
                gemini = "unavailable"
                metrics.incr(f"vision_error_{exc.reason}")
                log(logger, "vision_unavailable", logging.WARNING, reason=exc.reason)
        elif needs_gemini:
            gemini = "unavailable"

        if gemini_says is not None:
            contains, decided_by = gemini_says, "gemini"
        elif rule in {"yolo", "gemini"}:
            contains, decided_by = bool(shown), "detector"
        else:
            # Gemini was not needed (detector sure) or not available: the detector decides.
            contains, decided_by = score >= settings.verdict_yolo_high or (bool(shown) and detector_sure), "detector"

        if contains and decided_by == "gemini" and not shown:
            what = ", ".join(items[:3]) or "a plastic item"
            message = f"The AI check sees plastic ({what}) that the detector did not box. Retake it closer."
        elif contains and decided_by == "gemini":
            message = "Plastic confirmed by the AI check" + (f": {', '.join(items[:3])}." if items else ".")
        elif contains:
            message = "Plastic found by the detector."
        elif shown and decided_by == "gemini":
            message = "The AI check does not see plastic here, so the detector's box may be wrong."
        else:
            message = "No plastic found."
        return Verdict(
            contains_plastic=contains,
            rule=rule,
            decided_by=decided_by,
            detector_score=round(score, 4),
            gemini=gemini,
            plastic_items=items,
            message=message,
        )

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
    async def detect(request: Request, save: bool = False, verify: bool = False):
        """Find items in a photo. With save=true and an X-Client-Id header, the result (never the photo)
        is added to that browser's scan history."""
        app.state.limiter.check(rate_key(request), "detect", settings.detect_per_minute)
        await ensure_model(app)
        if app.state.detector is None:
            raise ApiError(503, "model_unavailable", "The detection model is not available.", retry_after_s=30)
        content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ApiError(415, "unsupported_media_type", "Send the image as image/jpeg, image/png or image/webp.")
        data = await read_body(request)

        async def produce() -> DetectResponse:
            detections, size, hints, elapsed, jpeg = await app.state.gate.run(run_detection, data, verify)
            metrics.observe("inference", elapsed)
            shown = [d for d in detections if classes[d.class_id] in enabled]
            item_word = enabled[0].lower() if len(enabled) == 1 else "waste"
            quality = assess(shown, classes, settings.low_confidence, competitors=detections, item_word=item_word)
            quality.image_hints = hints
            ranked = sorted(shown, key=lambda d: d.confidence, reverse=True)
            verdict = await decide(shown, jpeg) if verify else None
            scan_id = None
            client = history_client(request)
            if save and client and app.state.history is not None:
                record = ScanRecord(
                    model_version=app.state.detector.version,
                    quality=quality.status,
                    inference_ms=elapsed,
                    items=[ScanItem(classes[d.class_id], d.confidence) for d in ranked],
                )
                try:
                    scan_id = await asyncio.wait_for(
                        asyncio.to_thread(app.state.history.add, client, record), settings.database_timeout_s + 1
                    )
                    metrics.incr("history_saved")
                except (HistoryUnavailable, TimeoutError) as exc:  # the scan result matters more than history
                    metrics.incr("history_save_failed")
                    log(logger, "history_save_failed", logging.WARNING, reason=str(exc) or type(exc).__name__)
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
                scan_id=scan_id,
                verdict=verdict,
            )

        return await idempotent(request, "detect", hashlib.sha256(data).hexdigest(), produce)

    @app.post("/v1/guides", response_model=GuideResponse, tags=["guides"], responses=ERRORS)
    async def guides(request: Request, body: GuideRequest):
        app.state.limiter.check(rate_key(request), "guides", settings.guide_per_minute)
        if body.class_name.value not in enabled:
            raise ApiError(422, "class_not_enabled", f"This app only gives guides for: {', '.join(enabled)}.")

        async def produce() -> GuideResponse:
            request_body, identified = body.model_copy(update={"image": None}), None
            if body.image and not body.item_hint and app.state.vision is not None:
                identified = await identify(body.image)
                if identified is not None:
                    name, material, is_plastic, certainty = identified
                    if not is_plastic and certainty != "low" and body.class_name.value == "Plastic":
                        raise ApiError(
                            422,
                            "not_this_material",
                            f"This looks like {material} ({name}), not plastic. "
                            "Retake the photo or search for the item by name.",
                        )
                    request_body = request_body.model_copy(update={"item_hint": name})
            guide, cached = await app.state.guides.get(request_body)
            return GuideResponse(request_id=request_id_var.get(), guide=guide, cached=cached,
                                 identified_item=identified[0] if identified else None)

        fingerprint = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
        return await idempotent(request, "guides", fingerprint, produce)

    async def identify(image_b64: str) -> tuple[str, str, bool, str] | None:
        """Name the item in a crop. A Gemini failure falls back to a guide for the class alone."""
        try:
            image = decode_image(base64.b64decode(image_b64, validate=True), settings.max_pixels, 16)
        except Exception:
            raise ApiError(422, "invalid_image", "The item image could not be read.") from None
        try:
            answer = await app.state.vision.identify_item(to_jpeg(image, side=512))
        except VisionError as exc:
            metrics.incr(f"vision_error_{exc.reason}")
            log(logger, "identify_unavailable", logging.WARNING, reason=exc.reason)
            return None
        name = clean_item_name(answer.item_name)
        if not name:
            return None
        metrics.incr("vision_identified")
        return name, clean_item_name(answer.material) or "another material", answer.is_plastic, answer.certainty

    async def idempotent(request: Request, endpoint: str, fingerprint: str, produce) -> Response:
        key = request.headers.get("Idempotency-Key")
        if not key:
            result = await produce()
            return JSONResponse(result.model_dump(mode="json"))
        result, replayed = await app.state.idempotency.run(client_of(request), endpoint, key, fingerprint, produce)
        if replayed:
            metrics.incr(f"idempotent_replay_{endpoint}")
        headers = {"Idempotent-Replayed": str(replayed).lower()}
        if replayed:
            headers["X-Request-ID"] = result.request_id
        return JSONResponse(result.model_dump(mode="json"), headers=headers)

    def history_client(request: Request) -> str | None:
        client_id = request.headers.get(CLIENT_ID_HEADER, "")
        return client_id if REQUEST_ID_PATTERN.match(client_id) else None

    def history_for(request: Request) -> tuple[HistoryStore, str]:
        app.state.limiter.check(rate_key(request), "history", settings.history_per_minute)
        if app.state.history is None:
            raise ApiError(503, "history_disabled", "Scan history is not set up on this server.")
        client = history_client(request)
        if client is None:
            raise ApiError(400, "client_id_required", f"Send the {CLIENT_ID_HEADER} header to see your history.")
        return app.state.history, client

    async def history_call(fn, *args):
        try:
            return await asyncio.wait_for(asyncio.to_thread(fn, *args), settings.database_timeout_s * 2 + 1)
        except (HistoryUnavailable, TimeoutError) as exc:
            log(logger, "history_unavailable", logging.WARNING, reason=str(exc) or type(exc).__name__)
            raise ApiError(503, "history_unavailable", "Scan history is unavailable. Try again shortly.",
                           retry_after_s=10) from None

    @app.get("/v1/history", response_model=HistoryResponse, tags=["history"], responses=ERRORS)
    async def get_history(request: Request, limit: int = Query(20, ge=1, le=100)):
        """This browser's most recent saved scans, newest first, with totals."""
        store, client = history_for(request)
        scans = await history_call(store.recent, client, limit)
        stats = await history_call(store.stats, client)
        return HistoryResponse(scans=scans, you=stats["you"], everyone=stats["everyone"])

    @app.delete("/v1/history", tags=["history"], responses=ERRORS)
    async def clear_history(request: Request) -> dict:
        """Delete every saved scan of this browser."""
        store, client = history_for(request)
        return {"deleted": await history_call(store.clear, client)}

    catalog = Catalog()

    @app.get("/v1/items", tags=["items"])
    async def list_items(q: str | None = None) -> dict:
        """All coded items, or those matching a code, name or alias."""
        items = catalog.search(q) if q and q.strip() else catalog.items
        return {
            "version": catalog.version,
            "items": [CatalogSummary.model_validate(i.model_dump()).model_dump() for i in items],
        }

    @app.get("/v1/items/{code}", tags=["items"], responses=ERRORS)
    async def get_item(code: str) -> dict:
        item: CatalogItem | None = catalog.get(code)
        if item is None:
            raise ApiError(404, "item_not_found", f"No item has the code {code.strip()[:10]}.")
        return {**item.model_dump(), "safety_notice": SAFETY_NOTICE, "catalog_version": catalog.version}

    @app.get("/v1/metrics", tags=["ops"], include_in_schema=False)
    async def get_metrics(request: Request):
        token = settings.metrics_token.get_secret_value() if settings.metrics_token else ""
        supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not token or not hmac.compare_digest(supplied, token):
            raise ApiError(404, "not_found", "Not found.")
        snapshot = metrics.snapshot()
        snapshot["inference_in_flight"] = app.state.gate.in_flight
        return snapshot

    static_dir = settings.static_dir
    if static_dir and (static_dir / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            if "\x00" in path:
                raise ApiError(404, "not_found", "Not found.")
            try:
                candidate = (static_dir / path).resolve()
                if path and candidate.is_file() and candidate.is_relative_to(static_dir.resolve()):
                    return FileResponse(candidate)
            except (ValueError, OSError):
                raise ApiError(404, "not_found", "Not found.") from None
            if path.startswith(("v1/", "api/")):
                raise ApiError(404, "not_found", "Unknown API route.")
            if "." in Path(path).name:
                raise ApiError(404, "not_found", "Not found.")
            return FileResponse(static_dir / "index.html", headers={"Cache-Control": "no-cache"})

    return app
