# Paper API and worker images build on Debian 13 and run without build tools or a shell.
# The runtime's Python 3.13 ABI and /usr/bin/python path must match the build venv.
FROM ghcr.io/astral-sh/uv:0.12.23-python3.13-trixie-slim@sha256:a6aeb5c166af9f765f9c68e585b5a5148c28f3b8a362f90151cecea88b21a3e2 AS build

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
RUN ln -s /usr/local/bin/python /usr/bin/python \
    && /usr/bin/python -m venv /opt/venv \
    && /opt/venv/bin/python -c 'import sys; assert sys.prefix == "/opt/venv"'
RUN --mount=type=cache,target=/root/.cache/uv uv sync --all-packages --no-dev --frozen --python /usr/bin/python

FROM gcr.io/distroless/python3-debian13:nonroot@sha256:83aa8d4f74a4d7f7cf2d472054139bef71a927b76c680c0f2e1021d6b1d6d732 AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp
WORKDIR /app
COPY --from=build /app /app
COPY --from=build /opt/venv /opt/venv
USER 10001:10001
ENTRYPOINT ["/opt/venv/bin/python"]

FROM runtime AS api
EXPOSE 8000
CMD ["-m", "kavrigo_api"]

FROM runtime AS worker
CMD ["-m", "kavrigo_engine_worker"]
