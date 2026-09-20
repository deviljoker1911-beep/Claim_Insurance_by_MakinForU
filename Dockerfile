# ClaimAI as one container: the API serves the built web app on a single port.
#
# The OCR models ship inside the rapidocr package, so the image needs no network at run time and
# no API key. What it does need is a PostgreSQL URL and a writable volume for the originals it is
# given — those are never rebuilt from anything, so losing the volume loses the uploads.

# --- the web app -----------------------------------------------------------------------------
FROM node:22-slim AS web

WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


# --- the service -----------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# opencv-python is built against the GUI libraries even when nothing draws a window, and
# PyMuPDF wants the font config. Neither is optional at import time.
RUN apt-get update \
    && apt-get install --no-install-recommends -y libgl1 libglib2.0-0 fontconfig curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app/backend

# Dependencies resolve from the lock file alone, so this layer is rebuilt only when it changes.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

COPY backend/ /app/backend/
COPY demo_data/ /app/demo_data/
COPY --from=web /web/dist /app/frontend/dist

# The app writes originals and rendered pages here. Mount a volume over it: an image layer is
# not storage, and a container that is replaced takes an unmounted one with it.
RUN mkdir -p /app/backend/storage
VOLUME ["/app/backend/storage"]

ENV SERVE_FRONTEND=true \
    BACKEND_HOST=0.0.0.0 \
    BACKEND_PORT=8010 \
    APP_ENV=production \
    STORAGE_DIR=/app/backend/storage \
    DEMO_DATA_DIR=/app/demo_data \
    FRONTEND_DIST=/app/frontend/dist

EXPOSE 8010

# Reports the database too, so an orchestrator does not send traffic to a container that cannot
# answer. It stays up and serves /api/health while degraded, which is what makes this useful.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8010/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
