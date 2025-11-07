# Copilot Custom Instructions — fastapi-googleads (Codespaces)

## Purpose
You are assisting on a FastAPI + Google Ads backend (“Google API” project). Ground your answers in the repository and **ENVIRONMENT.md**. Prefer accurate, minimal diffs and preserve existing public interfaces.

## Canonical Docs (read first)
- **ENVIRONMENT.md** at repo root is the single source of truth (setup, hierarchy, routes, settings).
- If instructions conflict, **ENVIRONMENT.md wins**.

## Project Facts
- Python **3.12**, FastAPI, modular structure.
- Default Google Ads MCC: **7414394764**.
- Authentication: API key via `DASH_API_KEY`; OAuth for Google Ads; secrets via `.env` loaded early in `app/main.py` / `app/settings.py`.
- Core layout:
  - `app/main.py` (loads dotenv early)
  - `app/settings.py`
  - `app/deps/` (API key auth, etc.)
  - `app/services/` (`google_ads.py`, `oauth.py`, `usage_log.py`, tokens, OpenAI client)
  - `app/routers/` (`ads.py`, `auth.py`, `usage.py`, `misc.py`, `ops_fs.py`, `ops_archive.py`, `ops_patch.py`, `assist.py`, `googleads_proxy.py`)
  - `scripts/` (env checks, smoke tests, gateway helpers)
  - `.devcontainer/` (Codespaces config)
- Notable scripts:
  - `scripts/verify_env.py`, `scripts/env_check.py`, `scripts/smoke.py`
  - PowerShell helpers: `start_gateway.ps1`, `stop_gateway.ps1`, `test_gateway.ps1`

## How to Run (Codespaces)
- Launch server: `uvicorn app.main:APP --reload`
- Swagger UI: `http://127.0.0.1:8000/docs`
- Healthcheck: `GET /health`
- Use ngrok if public callback is needed (follow **ENVIRONMENT.md**).

## Windows Local Restart (quote these exact steps)
1) `cmd` → `cd %USERPROFILE%\Desktop\fastapi-googleads`
2) `venv\Scripts\activate`
3) `uvicorn app.main:APP --reload`
4) Open `http://127.0.0.1:8000/docs`

## Current Routes (auto-sourced)
| Method(s) | Path | Name |
|---|---|---|
| GET | `/` | home |
| GET | `/_routes` | list_routes |
| GET | `/ads/active-accounts` | list_active_accounts |
| GET | `/ads/customers` | list_customers |
| GET | `/ads/example-report` | example_report |
| GET | `/ads/keyword-ideas` | keyword_ideas |
| GET | `/ads/report-30d` | report_30d |
| GET | `/ads/report-ytd` | report_ytd |
| GET | `/ads/usage-log` | get_usage_log |
| GET | `/ads/usage-summary` | get_usage_summary |
| GET | `/auth/callback` | auth_callback |
| GET | `/auth/start` | auth_start |
| GET | `/debug/env` | debug_env |
| GET | `/docs` | swagger_ui_html |
| GET | `/docs/oauth2-redirect` | swagger_ui_redirect |
| GET | `/health` | health |
| GET | `/login` | login_set_cookie |
| GET | `/openapi.json` | openapi |
| GET | `/redoc` | redoc_html |

## Coding Style & Boundaries
- Keep PRs small and reviewable. Do not rename or remove existing public routes without explicit instruction.
- Never commit secrets; use `.env` and `app/settings.py`.
- Maintain idempotency for ETL (SQLAlchemy UPSERTs).

## Tests & Validation
- For Ads/OAuth changes: include a smoke run that opens `/docs` locally.
- For ETL: run loader with `--init` against a scratch DB and show a minimal diff summary.

## Assistant Behavior
- Cite specific files/lines from this repo in explanations.
- Offer migration steps when editing schemas and keep changes backward-compatible.
- If credentials/policy are implicated, ask for confirmation and point to **ENVIRONMENT.md**.