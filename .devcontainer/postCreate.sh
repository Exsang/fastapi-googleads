#!/usr/bin/env bash
set -euo pipefail

WS="/workspaces/fastapi-googleads"

echo "=== [postCreate] Creating venv ==="
mkdir -p "$WS/secrets/google_ads"
if [[ ! -d "$WS/.venv" ]]; then
  python -m venv "$WS/.venv"
fi
# shellcheck disable=SC1091
source "$WS/.venv/bin/activate"

echo "=== [postCreate] Upgrading pip tooling ==="
python -m pip install --upgrade pip wheel setuptools || true

echo "=== [postCreate] Installing project dependencies ==="
if [[ -f "$WS/requirements.txt" ]]; then
  pip install -r "$WS/requirements.txt"
else
  # Baseline deps if no requirements.txt yet (includes gRPC + protobuf)
  pip install \
    fastapi uvicorn[standard] python-dotenv pydantic pydantic-settings \
    google-ads grpcio grpcio-status protobuf sqlalchemy

  # Freeze the environment so future rebuilds are reproducible
  pip freeze > "$WS/requirements.txt"
fi

echo "=== [postCreate] Ensuring .env exists (non-destructive) ==="
if [[ ! -f "$WS/.env" ]]; then
  cat > "$WS/.env" <<EOF
HOST=0.0.0.0
PORT=8000
DEFAULT_SECRETS_DIR=$WS/secrets/google_ads
DEFAULT_MCC_ID=7414394764
EOF
  echo "[postCreate] Created minimal .env"
fi

# Provide a template with Google Ads keys if not present
if [[ ! -f "$WS/.env.template" ]]; then
  cat > "$WS/.env.template" <<'ENV'
# Copy to .env and fill in values.
# App basics
HOST=0.0.0.0
PORT=8000
DEFAULT_SECRETS_DIR=/workspaces/fastapi-googleads/secrets/google_ads
DEFAULT_MCC_ID=7414394764

# Google Ads API (required)
GOOGLE_ADS_DEVELOPER_TOKEN=
GOOGLE_ADS_CLIENT_ID=
GOOGLE_ADS_CLIENT_SECRET=
GOOGLE_ADS_REFRESH_TOKEN=
LOGIN_CUSTOMER_ID=7414394764

# App auth
DASH_API_KEY=
ENV
  echo "[postCreate] Wrote .env.template"
fi

echo "=== [postCreate] Running Google Ads smoke test ==="
python - <<'PY'
import os, sys
from google.ads.googleads.client import GoogleAdsClient
try:
    # Load from env (.env should be picked up by your app via python-dotenv at runtime;
    # for this smoke test we rely on real env vars if already set in the Codespace)
    client = GoogleAdsClient.load_from_env()
    svc = client.get_service("CustomerService")
    rns = list(svc.list_accessible_customers().resource_names)
    print("[SMOKE] CustomerService OK:", rns if rns else "No accounts visible (but call succeeded).")
except Exception as e:
    print("[SMOKE][WARN] Google Ads check did not succeed:", e)
    # Non-fatal: keep container usable even if creds aren't set yet
PY

echo "=== [postCreate] Finished. ==="
