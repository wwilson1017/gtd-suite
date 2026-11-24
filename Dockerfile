# todo-gtd — one image: the built frontend served by the FastAPI backend.

# ── 1. Build the frontend ────────────────────────────────────────────────────
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# vite.config.ts writes the build to ../backend/static, i.e. /app/backend/static.
RUN npm run build

# ── 2. The app ───────────────────────────────────────────────────────────────
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.11 /uv /bin/uv

# tzdata: every list has its own time zone, resolved through zoneinfo.
# age, zstd: compress and encrypt snapshots when SNAPSHOT_AGE_RECIPIENT is set (backend/backup.py).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata age zstd \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    DATA_DIR=/data

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev

COPY backend/ backend/
COPY scripts/ scripts/
COPY --from=frontend /app/backend/static backend/static

# Runs as root on purpose: a platform volume (Railway's) is mounted root-owned,
# and the app refuses to start when it cannot write DATA_DIR.
#
# Exactly ONE worker — the database's write lock is per process (backend/db.py).
# --no-proxy-headers: the client address is decided in one place only,
# backend/ratelimit.py's client_ip (TRUST_PROXY), not by uvicorn.
CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --no-proxy-headers"]
