# Project Context — FastAPI Google Ads Backend

## Overview
This repository implements a modular **FastAPI backend integrated with the Google Ads API**.  
It provides a secure, extensible framework for campaign reporting, keyword insights, OAuth management, and usage tracking.  
The project supports both **local (Windows)** and **GitHub Codespaces** development, with full environment portability.

---

## 1. Core Tech Stack

| Component | Purpose |
|------------|----------|
| **Python 3.12** | Main runtime |
| **FastAPI** | Web framework for serving endpoints |
| **SQLAlchemy** | ORM for SQLite / Postgres |
| **Google Ads API** | Fetch campaign, ad group, keyword, and search term data |
| **Ngrok** | Public URL exposure for OAuth callbacks |
| **dotenv (.env)** | Environment variable management |
| **Uvicorn** | Development ASGI server |
| **Makefile + scripts/** | Convenience helpers for startup, testing, and validation |

---

## 2. Authentication & Security

- **API Key Auth** via `DASH_API_KEY` handled in `app/deps/auth.py`
- **OAuth 2.0 Flow** for Google Ads
  - Tokens managed by `app/services/oauth.py`
  - Uses stored credentials from `.env` and Google’s secret JSONs
- `.env` file contains:
  ```
  GOOGLE_ADS_DEVELOPER_TOKEN=
  GOOGLE_CLIENT_ID=
  GOOGLE_CLIENT_SECRET=
  GOOGLE_REFRESH_TOKEN=
  DASH_API_KEY=
  ```
- Never commit credentials — only `.env.example` should exist in the repo.

---

## 3. Project Structure

```
app/
 ├── main.py              # Loads dotenv early, creates FastAPI app
 ├── settings.py          # Global constants + env variables
 ├── deps/
 │    └── auth.py         # API key validation dependency
 ├── routers/
 │    ├── ads.py          # Google Ads endpoints
 │    ├── auth.py         # OAuth start/callback endpoints
 │    ├── usage.py        # Usage tracking endpoints
 │    ├── misc.py         # Health and meta routes
 │    ├── ops_fs.py       # File system introspection
 │    ├── ops_archive.py  # Archival utilities
 │    ├── ops_patch.py    # Patch / maintenance tools
 │    ├── assist.py       # AI-assist route (OpenAI interface)
 │    ├── googleads_proxy.py  # Direct passthrough to Google Ads services
 ├── services/
 │    ├── google_ads.py       # Core Google Ads API client
 │    ├── oauth.py            # Handles token exchange and refresh
 │    ├── usage_log.py        # Logs endpoint usage
 │    ├── google_ads_token.py # Token refresh helpers
 │    └── openai_client.py    # Optional ChatGPT/OpenAI utilities
 └── deps/
      └── auth.py             # Bearer / API key dependency
```

---

## 4. Database Layer & ETL

- **Schema Files**
  - `schema_sqlite.sql`
  - `schema_postgres.sql`
- **ETL Script**
  - `etl_report_30d_loader.py`
  - Loads `/ads/report-30d`-style data from Google Ads
  - Performs **UPSERTS** for idempotent reloads
- **Tables**
  - `customers`
  - `campaigns`
  - `perf_daily_campaign`
  - `perf_daily_customer` (device & network mix)
  - `search_terms_daily`
- Supports **SQLite** (default local) or **Postgres** (persistent deployment).

---

## 5. Routes Summary

| Method | Endpoint | Description |
|--------|-----------|-------------|
| GET | `/` | Root / status page |
| GET | `/health` | Healthcheck |
| GET | `/ads/active-accounts` | List active accounts |
| GET | `/ads/customers` | Get customers |
| GET | `/ads/example-report` | Sample data response |
| GET | `/ads/report-30d` | 30-day campaign performance |
| GET | `/ads/keyword-ideas` | Keyword volume + CPC insights |
| GET | `/ads/usage-summary` | API usage summary |
| GET | `/auth/start` | Initiate OAuth flow |
| GET | `/auth/callback` | Handle OAuth callback |
| GET | `/ops/fs` | File system introspection |
| GET | `/docs` | Swagger UI |
| GET | `/redoc` | ReDoc UI |

---

## 6. Environment Details

### Local Windows Environment
**Restart Instructions**
1. `cmd` → `cd %USERPROFILE%\Desktop\fastapi-googleads`
2. `venv\Scripts\activate`
3. `uvicorn app.main:APP --reload`
4. Open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### Codespaces Environment
- Devcontainer automatically loads Copilot extensions:
  ```json
  {
    "extensions": ["GitHub.copilot", "GitHub.copilot-chat"]
  }
  ```
- Run server:  
  ```bash
  uvicorn app.main:APP --reload
  ```
- Public URL (when needed for OAuth): via ngrok (check ENVIRONMENT.md)

---

## 7. Automation & Logging

- `scripts/verify_env.py` → confirms .env keys and runtime config  
- `scripts/smoke.py` → performs `/health` and `/docs` checks  
- `start_gateway.ps1`, `stop_gateway.ps1`, `test_gateway.ps1` → Windows helper scripts for ngrok tunnel lifecycle  
- `ops/fs` endpoint → remote file listing for Codespaces introspection  
- Logging handled by `app/services/usage_log.py`, stored in lightweight DB

---

## 8. Integration Points

| System | Path | Purpose |
|---------|------|----------|
| **Google Ads API** | `/ads/*` | Customer, campaign, keyword data |
| **Ngrok** | `*.ngrok-free.dev` | Secure callback tunnel |
| **OpenAI (optional)** | `/assist` | Used for AI-assisted queries |
| **SQLAlchemy DB** | Local or persistent | Stores ETL data |

---

## 9. Development Notes

- All `.env` values are loaded early in `main.py`.
- Use `load_dotenv()` before any module imports that require secrets.
- Always test `/health` and `/docs` after each container rebuild.
- Avoid committing token files (inside `secrets/google_ads/`).

---

## 10. Maintenance & Extension

When adding new routes or features:
1. Add to the appropriate router (`app/routers/`).
2. Register route in `main.py`.
3. Document endpoint in **ENVIRONMENT.md**.
4. Update `.github/copilot-instructions.md` if behavior changes.
5. Run smoke test (`scripts/smoke.py`).

---

## 11. Copilot Context Integration

This document is part of the repo’s AI context bundle and should be referenced by:
- `.github/copilot-instructions.md` (for project context)
- `AGENTS.md` (for coding agent guidance)

Copilot Chat will automatically load this file in Codespaces, ensuring that:
- Suggestions follow your repo’s conventions and routes.
- Answers cite correct commands and endpoints.
- Generated code respects your authentication and `.env` model.

---

_Last updated: November 07, 2025_