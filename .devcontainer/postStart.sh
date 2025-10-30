#!/usr/bin/env bash
# Tolerant autostart — avoids breaking container boot
# Changes vs your version:
# - Don't use 'set -euo pipefail' (too strict for boot)
# - Guard optional steps with checks and '|| true'
# - Don't fail if port check tools are missing
# - Safer PID handling

WS="/workspaces/fastapi-googleads"
PID_DIR="$WS/.codespace"
LOG_DIR="$WS/logs"
PID_FILE="$PID_DIR/api.pid"
PORT="${PORT:-8000}"

# Don't let any single failure break container startup
set +e

mkdir -p "$PID_DIR" "$LOG_DIR" "$WS/secrets/google_ads"

# Ensure venv + deps (fast path if already installed)
if [ ! -d "$WS/.venv" ]; then
  python -m venv "$WS/.venv" || true
fi

# shellcheck disable=SC1091
source "$WS/.venv/bin/activate" 2>/dev/null || true

if [ -f "$WS/requirements.txt" ]; then
  pip install --upgrade pip wheel setuptools >/dev/null 2>&1 || true
  pip install -r "$WS/requirements.txt" >/dev/null 2>&1 || true
fi
if [ -f "$WS/requirements-dev.txt" ]; then
  pip install -r "$WS/requirements-dev.txt" >/dev/null 2>&1 || true
fi

# Create a stub .env if missing (non-secret defaults)
if [ ! -f "$WS/.env" ]; then
  cat > "$WS/.env" <<EOF
APP_VERSION=0.1.0
HOST=0.0.0.0
PORT=$PORT
DEFAULT_SECRETS_DIR=$WS/secrets/google_ads
DEFAULT_MCC_ID=7414394764
# GOOGLE_ADS_DEVELOPER_TOKEN=
# GOOGLE_ADS_CLIENT_ID=
# GOOGLE_ADS_CLIENT_SECRET=
# GOOGLE_ADS_REFRESH_TOKEN=
# DASH_API_KEY=
EOF
  echo "[postStart] Created stub .env at $WS/.env"
fi

# Avoid duplicate servers: if PID exists and is alive, skip
if [ -f "$PID_FILE" ]; then
  if ps -p "$(cat "$PID_FILE")" >/dev/null 2>&1; then
    echo "[postStart] API already running (PID $(cat "$PID_FILE")). Skipping autostart."
    exit 0
  else
    rm -f "$PID_FILE" || true
  fi
fi

# If 'ss' is available, check if port is in use; otherwise skip check
if command -v ss >/dev/null 2>&1; then
  if ss -ltn 2>/dev/null | awk '{print $4}' | grep -q ":$PORT$"; then
    echo "[postStart] Port $PORT already in use. Skipping autostart."
    exit 0
  fi
fi

# Start via Makefile in the background and capture PID safely
cd "$WS" || exit 0
# Run in login shell so .venv bins resolve; log to file
nohup bash -lc 'make run' >> "$LOG_DIR/api.log" 2>&1 & disown || true
PID=$!

if [ -n "$PID" ] && ps -p "$PID" >/dev/null 2>&1; then
  echo "$PID" > "$PID_FILE"
  echo "[postStart] Started API (PID $PID) — logs: $LOG_DIR/api.log"
else
  echo "[postStart] WARN: Could not determine API PID. Check logs at $LOG_DIR/api.log"
fi

# Never fail the container start
exit 0
