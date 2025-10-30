# ----- Variables -----
PY := .venv/bin/python
PIP := .venv/bin/pip
UVICORN := .venv/bin/uvicorn
BLACK := .venv/bin/black
RUFF := .venv/bin/ruff
PYTEST := .venv/bin/pytest

APP := app.main:APP
HOST ?= 0.0.0.0
PORT ?= 8000
ENV_FILE ?= .env

PID_FILE := .codespace/api.pid
LOG_FILE := logs/api.log

# ----- Phony -----
.PHONY: help venv install bootstrap dev run reload test lint format fix check clean freeze stop restart logs ensure_uvicorn

# ----- Help -----
help:
	@echo "Targets:"
	@echo "  make bootstrap    Create venv + install prod & dev deps"
	@echo "  make venv         Create virtualenv at .venv"
	@echo "  make install      Install requirements (+ requirements-dev.txt if present)"
	@echo "  make dev          Run API with reload (Uvicorn) on $(HOST):$(PORT) + proxy headers"
	@echo "  make run          Run API without reload"
	@echo "  make reload       Alias of 'dev'"
	@echo "  make test         Run pytest"
	@echo "  make lint         Ruff static checks"
	@echo "  make format       Black formatter"
	@echo "  make fix          Ruff --fix + Black"
	@echo "  make check        Lint + Test"
	@echo "  make clean        Remove caches"
	@echo "  make freeze       Write pinned deps to requirements.lock.txt"
	@echo "  make stop         Kill uvicorn (if running)"
	@echo "  make restart      Stop then dev"
	@echo "  make logs         Tail $(LOG_FILE)"

# ----- Env / install -----
venv:
	@test -d .venv || python -m venv .venv
	@$(PIP) -q install --upgrade pip wheel setuptools

install: venv
	@$(PIP) -q install -r requirements.txt || true
	@if [ -f requirements-dev.txt ]; then $(PIP) -q install -r requirements-dev.txt; fi

bootstrap: venv install
	@echo "Bootstrap complete ✅"

# Ensure uvicorn (and friends) exist in venv
ensure_uvicorn: venv
	@{ test -x "$(UVICORN)" || (echo "Installing uvicorn/fastapi/starlette/watchfiles into venv..." && $(PIP) install -q -U uvicorn fastapi starlette watchfiles); }

# ----- Run -----
dev: ensure_uvicorn
	@$(UVICORN) $(APP) --reload --host $(HOST) --port $(PORT) --env-file $(ENV_FILE) --proxy-headers

reload: dev

run: ensure_uvicorn
	@$(UVICORN) $(APP) --host $(HOST) --port $(PORT) --env-file $(ENV_FILE) --proxy-headers

# ----- Quality -----
test:
	@$(PYTEST) -q

lint:
	@$(RUFF) check .

format:
	@$(BLACK) .

fix:
	@$(RUFF) check . --fix
	@$(BLACK) .

check: lint test

# ----- Utilities -----
clean:
	@find . -type d -name "__pycache__" -exec rm -rf {} + || true
	@rm -rf .pytest_cache .ruff_cache .mypy_cache || true
	@echo "Clean complete 🧹"

freeze:
	@$(PIP) freeze > requirements.lock.txt
	@echo "Wrote requirements.lock.txt"

stop:
	@if pgrep -f "uvicorn.*$(APP)" >/dev/null 2>&1; then \
		echo "Stopping uvicorn..."; \
		pkill -f "uvicorn.*$(APP)" || true; \
	else \
		echo "No uvicorn process found."; \
	fi

restart: stop
	@$(MAKE) dev

logs:
	@mkdir -p logs
	@echo "Tailing $(LOG_FILE) (Ctrl+C to exit)"; \
	touch $(LOG_FILE); \
	tail -f $(LOG_FILE)
