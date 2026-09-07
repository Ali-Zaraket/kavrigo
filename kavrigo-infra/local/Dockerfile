# Local development image for the Python services.
#
# Production images are built separately with pinned digests, SBOM generation and Cosign
# signing (MASTER_BUILD_SPEC.md §24.4). This file is for the local stack only.

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

# Dependency layer: only the manifests, so a source edit does not re-resolve dependencies.
COPY pyproject.toml uv.lock* ./
COPY kavrigo-engine/libs/domain/pyproject.toml kavrigo-engine/libs/domain/
COPY kavrigo-engine/services/engine-worker/pyproject.toml kavrigo-engine/services/engine-worker/
COPY kavrigo-platform/services/api/pyproject.toml kavrigo-platform/services/api/
RUN uv sync --no-install-project --no-dev || true

COPY kavrigo-engine/libs/domain kavrigo-engine/libs/domain
COPY kavrigo-engine/services/engine-worker kavrigo-engine/services/engine-worker
COPY kavrigo-platform/services/api kavrigo-platform/services/api
RUN uv sync --no-dev

# Never run as root, even locally: it keeps the local image close to the production posture.
RUN useradd --create-home --uid 10001 kavrigo && chown -R kavrigo:kavrigo /app /opt/venv
USER kavrigo
ENV PATH="/opt/venv/bin:${PATH}"

FROM base AS api
EXPOSE 8000
CMD ["python", "-m", "kavrigo_api"]

FROM base AS worker
CMD ["python", "-m", "kavrigo_engine_worker"]
