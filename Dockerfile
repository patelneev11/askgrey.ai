# One image serves both halves: the SPA is built here and handed to the API process, so a
# deployment is a single container on a single origin and the browser never makes a cross-origin
# request (CORS_ORIGINS can stay empty). See docs/deployment.md.

FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Type errors fail the build here rather than shipping a bundle nobody type-checked.
RUN npm run build

FROM python:3.12-slim AS api
# RDKit's wheels are manylinux but still dynamically link these; without them the screening
# imports fail at start rather than at first use.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libxrender1 libxext6 curl \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    FRONTEND_DIST_DIR=/app/frontend-dist \
    PORT=8000

WORKDIR /app
# Dependencies resolve from pyproject alone, so a code-only change reuses this layer.
COPY backend/pyproject.toml ./
RUN python -m pip install --upgrade pip && python -m pip install .

COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./
# Reinstall so the package data (QSAR models, eligibility rules, personas) is present.
RUN python -m pip install --no-deps .
COPY --from=frontend /build/dist ./frontend-dist
COPY deploy/docker-entrypoint.sh /usr/local/bin/askgrey-entrypoint
RUN chmod +x /usr/local/bin/askgrey-entrypoint

# Nothing in the image needs to write to it; the stored papers live in S3 and the schema in RDS.
RUN useradd --create-home --uid 10001 askgrey
USER askgrey

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/api/health" > /dev/null || exit 1

ENTRYPOINT ["askgrey-entrypoint"]
