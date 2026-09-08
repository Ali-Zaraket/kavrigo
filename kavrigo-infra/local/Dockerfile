# Local development image for the Python services.
#
# Production images are built separately with pinned digests, SBOM generation and Cosign
# signing (MASTER_BUILD_SPEC.md §24.4). This file is for the local stack only.

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=300 \
    UV_CONCURRENT_DOWNLOADS=2 \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

# All workspace members must exist for uv to resolve the workspace. The previous three-
# package COPY silently failed its first sync and omitted every later engine library.
# Verified 2026-09-08: https://docs.astral.sh/uv/guides/integration/docker/
COPY pyproject.toml uv.lock* ./
COPY kavrigo-engine/libs kavrigo-engine/libs
COPY kavrigo-engine/services kavrigo-engine/services
COPY kavrigo-platform/services/api kavrigo-platform/services/api
# Keep completed downloads across interrupted builds on slow local links. These are local
# install settings, not runtime provider timeouts. Verified 2026-09-08:
# https://docs.astral.sh/uv/reference/environment/#uv_http_timeout
RUN --mount=type=cache,target=/root/.cache/uv uv sync --all-packages --no-dev

# Never run as root, even locally: it keeps the local image close to the production posture.
RUN useradd --create-home --uid 10001 kavrigo && chown -R kavrigo:kavrigo /app /opt/venv
USER kavrigo
ENV PATH="/opt/venv/bin:${PATH}"

FROM base AS api
EXPOSE 8000
CMD ["python", "-m", "kavrigo_api"]

FROM base AS worker
CMD ["python", "-m", "kavrigo_engine_worker"]
