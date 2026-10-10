.PHONY: check lint format type test test-fast eval serve demo generate

check: lint type test

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

type:
	uv run mypy

test:
	OMP_THREAD_LIMIT=1 uv run pytest

test-fast:
	OMP_THREAD_LIMIT=1 uv run pytest -o addopts= -m "not slow"

eval:
	uv run k1lens eval --fixtures fixtures/synthetic --report docs/eval-report.md --distribution in_distribution
	uv run k1lens eval --fixtures fixtures/dev --report docs/eval-report-dev.md --distribution dev
	uv run k1lens eval --fixtures fixtures/dev_b --report docs/eval-report-dev-b.md --distribution dev_b
	uv run k1lens eval --fixtures fixtures/dev_geometry --report docs/eval-report-dev-geometry.md --distribution dev_geometry

serve:
	uv run k1lens serve

demo:
	uv sync
	uv run k1lens serve

generate:
	uv run k1lens generate --out fixtures/synthetic --seed 1065 --count 14
	uv run k1lens generate --dev --out fixtures/dev --seed 1065
	uv run k1lens generate --dev-b --out fixtures/dev_b --seed 1065
	uv run k1lens generate --dev-geometry --out fixtures/dev_geometry --seed 1065
