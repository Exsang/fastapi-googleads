#!/usr/bin/env bash
set -e

WS="/workspaces/fastapi-googleads"

mkdir -p "$WS/secrets/google_ads"
if [ ! -d "$WS/.venv" ]; then
  python -m venv "$WS/.venv"
fi
source "$WS/.venv/bin/activate"

python -m pip install --upgrade pip wheel setuptools || true

if [ -f "$WS/requirements.txt" ]; then
  pip install -r "$WS/requirements.txt"
else
  pip install fastapi uvicorn[standard] python-dotenv pydantic pydantic-settings google-ads sqlalchemy
fi

# Minimal .env if missing
if [ ! -f "$WS/.env" ]; then
  cat > "$WS/.env" <<EOF
HOST=0.0.0.0
PORT=8000
DEFAULT_SECRETS_DIR=$WS/secrets/google_ads
DEFAULT_MCC_ID=7414394764
EOF
fi

echo "postCreate complete."
