# syntax=docker/dockerfile:1
# StockHub ETL image (Cloud Run Jobs). Build from the repo root:
#   docker build -f infra/Dockerfile -t stockhub-etl .

ARG PYTHON_VERSION=3.12

# ---------------------------------------------------------------- build
FROM python:${PYTHON_VERSION}-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src

# Dependencies first so code changes do not invalidate this layer.
COPY py/pyproject.toml py/uv.lock py/.python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

COPY py/stockhub ./stockhub
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

# ---------------------------------------------------------------- runtime
FROM python:${PYTHON_VERSION}-slim-bookworm
RUN groupadd --system --gid 10001 stockhub \
 && useradd --system --uid 10001 --gid stockhub --no-create-home --shell /usr/sbin/nologin stockhub
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    APP_ENV=production
WORKDIR /app
USER 10001:10001
ENTRYPOINT ["python", "-m", "stockhub.etl"]
CMD ["list"]
