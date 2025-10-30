# app/services/usage_log.py
from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

from ..settings import settings

LOG_PATH = Path("api_usage_log.csv")


def _ensure_log_header() -> None:
    if not LOG_PATH.exists():
        LOG_PATH.write_text(
            "ts,scope_id,request_id,endpoint,request_type,operations\n",
            encoding="utf-8",
        )


def log_api_usage(
    *,
    scope_id: str,
    request_id: Optional[str],
    endpoint: str,
    request_type: str,
    operations: int,
) -> None:
    _ensure_log_header()
    ts = datetime.now(timezone.utc).isoformat()
    with LOG_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([ts, scope_id, request_id or "", endpoint, request_type, operations])


def _read_all_rows() -> list[Dict[str, Any]]:
    if not LOG_PATH.exists():
        return []
    rows: list[Dict[str, Any]] = []
    with LOG_PATH.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def dashboard_stats(default_mcc_id: str) -> Dict[str, Any]:
    """
    Summarize today's and all-time usage from the local CSV log.
    Pulls caps from settings (Pydantic), replacing old GET_CAP/OPS_CAP constants.
    """
    rows = _read_all_rows()

    # Caps now come from settings
    get_cap = settings.BASIC_DAILY_GET_REQUEST_LIMIT
    ops_cap = settings.BASIC_DAILY_OPERATION_LIMIT

    total_usage_rows = len(rows)
    today = datetime.now(timezone.utc).date()

    today_usage_rows = 0
    today_get_requests = 0
    today_operations = 0

    for r in rows:
        try:
            ts = datetime.fromisoformat(r["ts"])
        except Exception:
            # skip malformed rows
            continue
        if ts.date() == today:
            today_usage_rows += 1
            if (r.get("request_type") or "").lower() == "get":
                today_get_requests += 1
            try:
                today_operations += int(r.get("operations") or 0)
            except ValueError:
                pass

    return {
        "total_usage_rows": total_usage_rows,
        "today_usage_rows": today_usage_rows,
        "today_get_requests": today_get_requests,
        "today_operations": today_operations,
        "get_cap": get_cap,
        "ops_cap": ops_cap,
        "default_mcc_id": default_mcc_id,
    }
