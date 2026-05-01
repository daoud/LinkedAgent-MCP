.PHONY: up down logs migrate seed dev test test-all lint format clean

PYTHON  := venv/bin/python
ALEMBIC := venv/bin/alembic
PYTEST  := venv/bin/pytest
RUFF    := venv/bin/ruff
BLACK   := venv/bin/black

# ---- Docker ----------------------------------------------------------------

up:
	docker compose up -d
	@echo "Waiting for PostgreSQL to be ready..."
	@until docker compose exec -T postgres pg_isready -U pipeline -d pipeline >/dev/null 2>&1; do \
		printf '.'; sleep 1; \
	done
	@echo " ready."

down:
	docker compose down

logs:
	docker compose logs -f postgres

# ---- Database --------------------------------------------------------------

migrate:
	$(ALEMBIC) upgrade head

seed:
	$(PYTHON) scripts/seed_prompt_template.py

# ---- Development -----------------------------------------------------------

dev:
	$(PYTHON) -m uvicorn src.api.app:app --reload --port 8000

# ---- Tests -----------------------------------------------------------------

test:
	$(PYTEST) tests/unit/ -v --tb=short

test-all:
	$(PYTEST) -v --tb=short

# ---- Code Quality ----------------------------------------------------------

lint:
	$(RUFF) check src tests scripts

format:
	$(BLACK) src tests scripts
	$(RUFF) check --fix src tests scripts

# ---- Cleanup ---------------------------------------------------------------

clean:
	docker compose down -v
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
