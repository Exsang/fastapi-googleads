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

# ----- Phony -----
.PHONY: help venv install bootstrap dev run reload test lint format fix check clean freeze

# ----- Help -----
help:
	@echo "Targets:"
	@echo "  make bootstrap    Create venv + install prod & dev deps"
	@echo "  make venv         Create virtualenv at .venv"
	@echo "  make install      Install requirements (+ requirements-dev.txt if present)"
	@echo "  make dev          Run API with reload (Uvicorn) on $(HOST):$(PORT)"
	@echo "  make run          Run API without reload"
	@echo "  make reload       Alias of 'dev'"
	@echo "  make test         Run pytest"
	@echo "  make lint         Ruff static checks"
	@echo "  make format       Black formatter"
	@echo "  make fix          Ruff --fix + Black"
	@echo "  make check        Lint + Test"
	@echo "  make clean        Remove caches"
	@echo "  make freeze       Write pinned deps to requirements.lock.txt"

# ----- Env / install -----
venv:
	@test -d .venv || python -m venv .venv
	@$(PIP) -q install --upgrade pip wheel setuptools

install: venv
	@$(PIP) -q install -r requirements.txt
	@if [ -f requirements-dev.txt ]; then $(PIP) -q install -r requirements-dev.txt; fi

bootstrap: venv install
	@echo "Bootstrap complete ✅"

# ----- Run -----
dev:
	@$(UVICORN) $(APP) --reload --host $(HOST) --port $(PORT) --env-file $(ENV_FILE)

reload: dev

run:
	@$(UVICORN) $(APP) --host $(HOST) --port $(PORT) --env-file $(ENV_FILE)

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

PID_FILE := .codespace/api.pid
LOG_FILE := logs/api.log

.PHONY: stop restart logs

stop:
	@if [ -f $(PID_FILE) ]; then \
		PID=$$(cat $(PID_FILE)); \
		if ps -p $$PID >/dev/null 2>&1; then \
			echo "Stopping API (PID $$PID)"; \
			kill $$PID || true; \
			sleep 1; \
		fi; \
		rm -f $(PID_FILE); \
	else \
		echo "No PID file found; nothing to stop."; \
	fi

restart: stop
	@$(MAKE) dev

logs:
	@mkdir -p logs
	@echo "Tailing $(LOG_FILE) (Ctrl+C to exit)"; \
	touch $(LOG_FILE); \
	tail -f $(LOG_FILE)
