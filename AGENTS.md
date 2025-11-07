# AGENTS — fastapi-googleads

## Build/Run
- Use Python 3.12.
- Launch: `uvicorn app.main:APP --reload`
- Open `http://127.0.0.1:8000/docs`

## Tasks You May Perform
- Add non-breaking endpoints under `app/routers/`.
- Update ETL SQLAlchemy models with idempotent migrations and UPSERTs.
- Improve `ENVIRONMENT.md` when commands/paths/settings change.
- Create minimal smoke tests for new routes.

## Validation Steps (per change)
- Start the server and confirm `/health` and `/docs` work.
- If touching `/ads/*` or OAuth, run `scripts/verify_env.py` (or `scripts/smoke.py`) and report output.
- For ETL changes, run the loader with `--init` on a temp DB and summarize affected tables/rows.

## Guardrails
- Do not commit secrets.
- Do not remove or rename public routes without explicit instruction.
- Preserve existing folder layout and dependency loading order (dotenv early).