# ENVIRONMENT (Single Source of Truth)

> Keep this file updated. Manual notes go above; the script updates the auto section below.

## Manual Notes (edit me)
- Project: FastAPI + Google Ads backend
- Default MCC: 7414394764
- Python: 3.12
- Start:
  1) cd %USERPROFILE%\Desktop\fastapi-googleads
  2) venv\Scripts\activate
  3) uvicorn app.main:APP --reload
  4) Open http://127.0.0.1:8000/docs

---

## Auto-Generated Summary (do not edit below)
<!-- BEGIN AUTO -->
_Generated at: **2025-10-27 15:56:12**  |  **no-git**_

**Routes:** 19  •  **Namespaces:** ads, auth, debug

### Routes (live)
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

### Settings snapshot (selected)
```
{
  "DEFAULT_MCC_ID": "7414394764",
  "LOGIN_CID": "7414394764",
  "DEV_TOKEN": "ogPE…1oKQ",
  "DASH_API_KEY": null
}
```

### Package versions
```
{
  "fastapi": "0.119.1",
  "uvicorn": "0.38.0",
  "google-ads": "28.2.0",
  "pydantic": "2.12.0"
}
```

### Folder tree (depth 2)
```
- app/
  - deps/
    - __init__.py
    - auth.py
  - routers/
    - __init__.py
    - ads.py
    - auth.py
    - misc.py
    - usage.py
  - services/
    - __init__.py
    - google_ads.py
    - oauth.py
    - usage_log.py
  - __init__.py
  - main.py
  - settings.py
- scripts/
  - generate_env_summary.py
- api_usage_log.csv
- ENVIRONMENT.md
- google_oauth_client.json
- start_gateway.ps1
- start_server_with_ngrok.bat.txt
- stop_gateway.ps1
- test_gateway.ps1
```
<!-- END AUTO -->
