# aicut — dev ergonomics. Portable Python scripts do the real work so this
# works whether or not GNU make is installed (Windows: `python scripts/dev.py`).

.PHONY: dev check test lint typecheck fmt doctor install frontend-install export-clean

dev:
	python scripts/dev.py

check:
	python scripts/check.py

test:
	uv run pytest -q

lint:
	uv run ruff check backend tests scripts

fmt:
	uv run ruff format backend tests scripts
	uv run ruff check --fix backend tests scripts

typecheck:
	cd frontend && npm run typecheck

doctor:
	uv run python -m aicut doctor

install:
	uv sync
	cd frontend && npm install

frontend-install:
	cd frontend && npm install
