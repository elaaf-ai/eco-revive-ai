# syntax=docker/dockerfile:1.7
# One container serves the website and the API from the same origin (no CORS needed in production).

FROM node:24.22.3-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npx tsc -b && npx vite build

FROM python:3.14.10-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ECOREVIVE_STATIC_DIR=/app/web/dist \
    ECOREVIVE_MODEL_DIR=/app/models/current
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-deps -r requirements.txt && useradd --create-home --uid 10001 app
COPY shared/ /app/shared/
COPY backend/app/ ./app/
COPY backend/scripts/fetch_model.py ./scripts/fetch_model.py
COPY models/registry/ /app/models/registry/
COPY --from=web /web/dist /app/web/dist

# The model is not in the image by default. Either mount it at /app/models/current, or set
# MODEL_VERSION and MODEL_BASE_URL so the entrypoint downloads it and verifies its checksum.
RUN mkdir -p /app/models/current && chown -R app /app/models
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"
CMD ["sh", "-c", "if [ -n \"$MODEL_VERSION\" ] && [ ! -f /app/models/current/model.onnx ]; then python scripts/fetch_model.py --version \"$MODEL_VERSION\" --out /app/models/current || exit 1; fi; exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips=${FORWARDED_ALLOW_IPS:-127.0.0.1} --timeout-graceful-shutdown 20"]
