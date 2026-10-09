# Paper API and worker images share a pinned Python/uv base and the exact uv lock.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim@sha256:531f855bda2c73cd6ef67d56b733b357cea384185b3022bd09f05e002cd144ca AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY kavrigo-engine/libs kavrigo-engine/libs
COPY kavrigo-engine/services kavrigo-engine/services
COPY kavrigo-platform/services/api kavrigo-platform/services/api
RUN --mount=type=cache,target=/root/.cache/uv uv sync --all-packages --no-dev --frozen
RUN useradd --create-home --uid 10001 kavrigo && chown -R kavrigo:kavrigo /app /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
USER 10001:10001

FROM base AS api
EXPOSE 8000
CMD ["python", "-m", "kavrigo_api"]

FROM base AS worker
CMD ["python", "-m", "kavrigo_engine_worker"]
