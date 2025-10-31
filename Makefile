# Default network config (fallback if .env is missing or unset)
HOST ?= 0.0.0.0
PORT ?= 8000
ENV_FILE ?= .env

# Make sure we use bash and inherit the environment
SHELL := /bin/bash
export

# ----- Tool paths (ensure these are defined) -----
PY := .venv/bin/python
PIP := .venv/bin/pip
UVICORN := .venv/bin/uvicorn
BLACK := .venv/bin/black
RUFF := .venv/bin/ruff
PYTEST := .venv/bin/pytest

# ----- Virtualenv + install helpers -----
.PHONY: venv install bootstrap

venv:
	@echo "Creating virtual environment at .venv (if missing)…"
	@test -d .venv || python -m venv .venv
	@.venv/bin/pip -q install --upgrade pip wheel setuptools

install: venv
	@echo "Installing requirements…"
	@.venv/bin/pip -q install -r requirements.txt || true
	@if [ -f requirements-dev.txt ]; then .venv/bin/pip -q install -r requirements-dev.txt; fi

bootstrap: install
	@echo "Bootstrap complete ✅"

# ----- Dependency & env helpers -----
.PHONY: ensure_deps ensure_tools doctor smoke

ensure_deps: venv
	@echo "Ensuring runtime deps in venv…"
	@$(PIP) install -q -U \
		fastapi uvicorn[standard] starlette watchfiles python-dotenv \
		pydantic pydantic-settings \
		google-ads grpcio grpcio-status protobuf \
		sqlalchemy

ensure_tools: venv
	@echo "Ensuring dev tools in venv…"
	@$(PIP) install -q -U ruff black pytest

doctor: ensure_deps
	@echo "Checking required env vars…"
	@set -a; \
	[[ -f .env ]] && source .env || true; \
	set +a; \
	printenv | grep -E 'GOOGLE_ADS_|LOGIN_CUSTOMER_ID' || true; \
	$(PY) scripts/env_check.py || true; \
	echo "Running CustomerService smoke test…"; \
	$(PY) scripts/smoke.py

smoke: ensure_deps
	@$(PY) scripts/smoke.py

# ----- Run / serve API -----
.PHONY: dev run reload

dev: ensure_uvicorn
	@echo "Starting FastAPI server with reload on $(HOST):$(PORT)…"
	@$(UVICORN) $(APP) --reload --host $(HOST) --port $(PORT) --env-file $(ENV_FILE) --proxy-headers

# ----- Ensure runtime deps -----
.PHONY: ensure_uvicorn ensure_deps ensure_tools doctor dev

# Create venv if missing
venv:
	@echo "Creating virtual environment at .venv (if missing)…"
	@test -d .venv || python -m venv .venv
	@.venv/bin/pip -q install --upgrade pip wheel setuptools

# Ensure uvicorn and FastAPI exist
ensure_uvicorn: venv
	@echo "Ensuring uvicorn and FastAPI runtime deps…"
	@.venv/bin/pip install -q -U uvicorn fastapi starlette watchfiles python-dotenv

# ----- Run development server -----
dev: ensure_uvicorn
	@echo "Starting FastAPI server with reload on $(HOST):$(PORT)…"
	@.venv/bin/uvicorn app.main:APP --reload --host $(HOST) --port $(PORT) --env-file $(ENV_FILE) --proxy-headers


run: ensure_deps
	@echo "Starting FastAPI server (no reload)…"
	@$(UVICORN) app.main:APP --host $(HOST) --port $(PORT) --env-file .env --proxy-headers

reload: dev
