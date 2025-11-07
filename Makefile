# ---------------------------------------------------------------------
# Export the FastAPI project into a compressed archive
# ---------------------------------------------------------------------
export:
	@echo "📦 Creating project archive..."
	@mkdir -p _exports
	@tar --exclude='.git*' \
	     --exclude='__pycache__' \
	     --exclude='*.pyc' \
	     --exclude='*.pyo' \
	     --exclude='*.db' \
	     --exclude='*.sqlite' \
	     --exclude='*.log' \
	     --exclude='node_modules' \
	     --exclude='.venv' \
	     --exclude='venv' \
	     -czf "_exports/fastapi-googleads-$(shell date +%Y%m%d-%H%M%S).tar.gz" .
	@echo "✅ Archive created in _exports/"
	@ls -lh _exports | tail -n 5


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
APP_MODULE := app.main:APP

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
	@$(UVICORN) $(APP_MODULE) --reload --host $(HOST) --port $(PORT) --env-file $(ENV_FILE) --proxy-headers

# ----- Ensure runtime deps -----
.PHONY: ensure_uvicorn

# Ensure uvicorn and FastAPI exist (lightweight install for dev server)
ensure_uvicorn: venv
	@echo "Ensuring uvicorn and FastAPI runtime deps…"
	@$(PIP) install -q -U uvicorn fastapi starlette watchfiles python-dotenv


run: ensure_deps
	@echo "Starting FastAPI server (no reload)…"
	@$(UVICORN) app.main:APP --host $(HOST) --port $(PORT) --env-file .env --proxy-headers

reload: dev

# ----- Git Tagging Utilities -----
.PHONY: tag tags list_tags

# Usage:
#   make tag VERSION=v0.2.0 MESSAGE="add dashboard endpoints"
tag:
	@if [ -z "$(VERSION)" ]; then echo "❌ VERSION is required (e.g., make tag VERSION=v0.2.0 MESSAGE='desc')"; exit 1; fi
	@if [ -z "$(MESSAGE)" ]; then echo "❌ MESSAGE is required"; exit 1; fi
	@echo "🏷️  Creating annotated tag: $(VERSION)"
	git tag -a $(VERSION) -m "$(MESSAGE)"
	@echo "📤 Pushing tag $(VERSION) to origin..."
	git push origin $(VERSION)
	@echo "✅ Tag $(VERSION) created and pushed."

# List all tags
list_tags:
	@echo "🏷️  Available Git tags:"
	git tag -l --sort=-creatordate | head -20

# ----- Release Utilities -----
.PHONY: release release-dry ensure_clean _bump_version

# Usage:
#   make release VERSION=v0.2.0 MESSAGE="add dashboard endpoints"
#   make release-dry VERSION=v0.2.0 MESSAGE="preview new version bump"

release: _bump_version
	@if [ -z "$(VERSION)" ]; then echo "❌ VERSION is required (e.g., make release VERSION=v0.2.0 MESSAGE='desc')"; exit 1; fi
	@if [ -z "$(MESSAGE)" ]; then echo "❌ MESSAGE is required"; exit 1; fi
	@echo "📝 Committing version bump for $(VERSION)…"
	git add app/settings.py
	git commit -m "release($(VERSION)): $(MESSAGE)" || echo "ℹ️  Nothing to commit (version already set?)"
	@echo "🏷️  Tagging $(VERSION)…"
	git tag -a $(VERSION) -m "$(MESSAGE)" || echo "ℹ️  Tag already exists?"
	@echo "📤 Pushing main + tag…"
	git push origin main
	git push origin $(VERSION) || true
	@echo "✅ Release $(VERSION) is live."

# Dry run (preview only — does not write, commit, or push)
release-dry:
	@if [ -z "$(VERSION)" ]; then echo "❌ VERSION is required (e.g., make release-dry VERSION=v0.2.0)"; exit 1; fi
	@echo "🔍 Preview: settings.py current line:" ; grep -n 'APP_VERSION' app/settings.py | head -1 || true
	@echo "🧪 Would run: sed -i -E 's/(APP_VERSION\", \")[^\"]+(\"))/\\1$(VERSION)\\2/' app/settings.py"
	@echo "🔍 Preview: .env status:" ; [ -f .env ] && (grep -n '^APP_VERSION=' .env || echo '<no APP_VERSION in .env>') || echo '<no .env file present>'
	@echo "🧪 Would update .env APP_VERSION= to $(VERSION) (append if missing)."
	@echo "🧾 No changes made — dry run only."

# Internal helper: bump version string in settings.py AND .env (if present)
_bump_version:
	@if [ -z "$(VERSION)" ]; then echo "❌ VERSION is required (e.g., v0.2.0)"; exit 1; fi
	@echo "🔧 Updating app/settings.py APP_VERSION → $(VERSION)"
	@# Example line we target: APP_VERSION: str = os.getenv("APP_VERSION", "0.1.0")
	@sed -i -E 's/(APP_VERSION", ")[^"]+(")/\1$(VERSION)\2/' app/settings.py
	@echo "✅ settings.py now:" ; grep -n 'APP_VERSION' app/settings.py | head -1

	@echo "🔧 Syncing .env APP_VERSION (if .env exists)…"
	@# Only touch .env if the file exists; it’s gitignored, so this is safe for local runtime.
	@if [ -f .env ]; then \
	  if grep -qE '^APP_VERSION=' .env; then \
	    sed -i -E 's/^APP_VERSION=.*/APP_VERSION=$(VERSION)/' .env; \
	  else \
	    printf "\nAPP_VERSION=$(VERSION)\n" >> .env; \
	  fi; \
	  echo "✅ .env now:" ; grep -n '^APP_VERSION=' .env | tail -1 ; \
	else \
	  echo "ℹ️  .env not found — skipping .env update (runtime can still override via env)."; \
	fi
.PHONY: smoke-http patch-sample

smoke-http:
	curl -s -X POST "http://127.0.0.1:8000/assist/chat" \\
	  -H "Content-Type: application/json" -H "x-api-key: $$DASH_API_KEY" \\
	  -d '{ "messages":[{"role":"user","content":"ping"}], "stream": false }' | jq .

patch-sample:
	curl -s -X POST "http://127.0.0.1:8000/ops/patch" \\
	  -H "Content-Type: application/json" -H "x-api-key: $$DASH_API_KEY" \\
	  -d @sample_patch.json | jq .
