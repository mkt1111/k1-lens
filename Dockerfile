FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    OMP_THREAD_LIMIT=1

COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
COPY fixtures/README.md ./fixtures/README.md
RUN uv sync --frozen --no-dev --no-editable \
    && uv run k1lens generate --out fixtures/synthetic --seed 1065 --count 14 \
    && uv run k1lens generate --dev --out fixtures/dev --seed 1065 \
    && uv run k1lens generate --dev-b --out fixtures/dev_b --seed 1065 \
    && uv run k1lens generate --dev-geometry --out fixtures/dev_geometry --seed 1065 \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin k1lens \
    && mkdir -p /app/data \
    && chown -R k1lens:k1lens /app

USER k1lens

EXPOSE 8000
CMD ["k1lens", "serve", "--host", "0.0.0.0", "--port", "8000"]
