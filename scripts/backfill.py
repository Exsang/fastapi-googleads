#!/usr/bin/env python3
from __future__ import annotations
import argparse
import sys
import os
from datetime import date, datetime, timedelta
from typing import List

# Ensure app package import works when running as a script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.db.session import SessionLocal  # type: ignore  # noqa: E402
from app.services.etl_google_ads import ingest_multi_level_day  # type: ignore  # noqa: E402


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _daterange(start: date, end: date):
    # inclusive of end
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def main():
    parser = argparse.ArgumentParser(
        description="Backfill Google Ads daily performance into Postgres")
    parser.add_argument(
        "customer_id", help="Google Ads Customer ID (with or without dashes)")
    parser.add_argument("--start", dest="start",
                        help="Start date YYYY-MM-DD (default: Jan 1 of current year)")
    parser.add_argument("--end", dest="end",
                        help="End date YYYY-MM-DD (default: today)")
    parser.add_argument("--levels", dest="levels", default="campaign,ad_group,ad,keyword",
                        help="Comma-separated levels to ingest")
    parser.add_argument("--dry-run", dest="dry_run",
                        action="store_true", help="Plan only; do not write to DB")

    args = parser.parse_args()

    today = date.today()
    start = _parse_date(args.start) if args.start else date(today.year, 1, 1)
    end = _parse_date(args.end) if args.end else today
    if end < start:
        parser.error("End date must be >= start date")

    levels: List[str] = [s.strip().lower()
                         for s in (args.levels or "").split(',') if s.strip()]
    if not levels:
        parser.error("At least one level must be specified")

    print(f"Backfill start={start} end={end} levels={levels}")

    if args.dry_run:
        print("Dry run only; exiting")
        return 0

    total_rows = 0
    with SessionLocal() as db:
        for d in _daterange(start, end):
            try:
                result = ingest_multi_level_day(
                    db, args.customer_id, d, levels)
                db.commit()
                day_rows = result.get("total_rows", 0)
                total_rows += int(day_rows or 0)
                print(f"{d.isoformat()}: ok rows={day_rows}")
            except Exception as e:
                db.rollback()
                print(f"{d.isoformat()}: ERROR {e}", file=sys.stderr)
    print(f"Done. Total rows upserted: {total_rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
