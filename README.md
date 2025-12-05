# fastapi-googleads

## Repository refresh note

Repository refreshed on 2025-12-05 UTC to record activity and help avoid automated cleanup due to inactivity. This change is intentionally small and non-breaking (adds a keepalive file under `.github/`).

## Scheduled keepalive workflow

This repository includes a small GitHub Actions workflow at `.github/workflows/keepalive.yml` that runs weekly (Sunday 00:00 UTC) and can be triggered manually from the Actions UI. The workflow updates `.github/KEEPALIVE.md` with a UTC timestamp and makes a small commit with the message "chore: periodic keepalive commit [skip ci]".

What it does:
- Runs on a weekly cron schedule and via `workflow_dispatch` (manual trigger).
- Updates `.github/KEEPALIVE.md` with the current UTC timestamp and commits the change using the runner's credentials.
- Uses `[skip ci]` in the commit message to avoid triggering CI workflows.

Notes:
- If your repository uses branch protection rules that block pushes from the `GITHUB_TOKEN`, the workflow can be changed to open a PR instead of pushing directly — tell me if you'd like that.
- To change the cadence, edit the cron expression in `.github/workflows/keepalive.yml`.

