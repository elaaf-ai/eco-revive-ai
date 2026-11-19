# Hugging Face Docker Space: website + API in one container, model baked in (checksum-verified
# by deploy/deploy_hf_space.py before upload). Runs as UID 1000 on port 7860, as Spaces require.

FROM node:24.22.3-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npx tsc -b && npx vite build

FROM python:3.14.10-slim-bookworm
RUN useradd -m -u 1000 user
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/user \
    ECOREVIVE_STATIC_DIR=/home/user/app/web/dist \
    ECOREVIVE_MODEL_DIR=/home/user/app/models/current
WORKDIR /home/user/app/backend
COPY backend/requirements.txt ./
RUN pip install --no-deps -r requirements.txt
USER user
COPY --chown=user shared/ /home/user/app/shared/
COPY --chown=user backend/app/ ./app/
COPY --chown=user models/current/ /home/user/app/models/current/
COPY --chown=user --from=web /web/dist /home/user/app/web/dist
EXPOSE 7860
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "7860", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips=*", "--timeout-graceful-shutdown", "20"]
