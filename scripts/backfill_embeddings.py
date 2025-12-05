#!/usr/bin/env python3
"""Backfill embeddings for Google Ads entities.

Usage (examples):
  python scripts/backfill_embeddings.py --customer 1234567890 --levels campaign ad_group keyword --model text-embedding-3-small
  python scripts/backfill_embeddings.py --customer 1234567890 --search-terms --days 30

The script pulls month-to-date (THIS_MONTH) metrics for each requested level and
creates a compact text payload embedding rows into the `embedding` table.
Idempotent: re-running will skip unchanged chunk hashes.

Levels supported: campaign, ad_group, ad, keyword
Optional: search terms over LAST_N_DAYS via --search-terms

Environment requirements: Google Ads credentials and (optionally) OPENAI_API_KEY.
If OPENAI_API_KEY is missing, zero-vectors will be stored (still useful for later re-embed).

Exit codes:
  0 success (even if 0 rows inserted)
  2 invalid arguments
  3 Google Ads query error
"""
from __future__ import annotations
import argparse
import sys
from typing import List, Dict, Any

from app.db.session import SessionLocal
from app.services.embeddings import upsert_embeddings_for_entity, backfill_search_terms_for_customer
from app.services.google_ads import run_mtd_level_report
from app.services.openai_client import hash_text

# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _build_text(level: str, row: Dict[str, Any]) -> str:
    level = level.lower()
    if level == 'campaign':
        return (f"Campaign {row.get('campaign_id')} '{row.get('name')}'. Status {row.get('status')}. "
                f"MTD impressions {row.get('impressions')}, clicks {row.get('clicks')}, cost {row.get('cost')} USD, "
                f"conversions {row.get('conversions')}, conv_value {row.get('conv_value')}.")
    if level == 'ad_group':
        return (f"Ad group {row.get('ad_group_id')} '{row.get('ad_group_name')}' in campaign {row.get('campaign_id')} '{row.get('campaign_name')}'. Status {row.get('status')}. "
                f"MTD impressions {row.get('impressions')}, clicks {row.get('clicks')}, cost {row.get('cost')} USD, conversions {row.get('conversions')}, conv_value {row.get('conv_value')}.")
    if level == 'ad':
        return (f"Ad {row.get('ad_id')} type {row.get('ad_type')} status {row.get('status')} in ad group {row.get('ad_group_id')} campaign {row.get('campaign_id')}. "
                f"MTD impressions {row.get('impressions')}, clicks {row.get('clicks')}, cost {row.get('cost')} USD, conversions {row.get('conversions')}, conv_value {row.get('conv_value')}.")
    if level == 'keyword':
        return (f"Keyword '{row.get('text')}' match {row.get('match_type')} status {row.get('status')} in ad group {row.get('ad_group_id')} campaign {row.get('campaign_id')}. "
                f"MTD impressions {row.get('impressions')}, clicks {row.get('clicks')}, cost {row.get('cost')} USD, conversions {row.get('conversions')}, conv_value {row.get('conv_value')}.")
    return f"Unsupported level {level}"  # defensive fallback


def _embed_level(customer_id: str, level: str, model: str | None, limit: int | None) -> Dict[str, Any]:
    report = run_mtd_level_report(customer_id, level=level)
    if not report.get('ok'):
        return {"ok": False, "error": report.get('error', 'unknown error'), "level": level}
    rows = report.get('rows', [])
    if limit is not None:
        rows = rows[:max(0, int(limit))]
    db = SessionLocal()
    inserted = 0
    skipped = 0
    sample_ids: List[int] = []
    try:
        for r in rows:
            # deterministic entity id using hash of identifying fields
            if level == 'campaign':
                entity_id_raw = f"c:{r.get('campaign_id')}"
                title = r.get('name')
            elif level == 'ad_group':
                entity_id_raw = f"ag:{r.get('ad_group_id')}"
                title = r.get('ad_group_name')
            elif level == 'ad':
                entity_id_raw = f"ad:{r.get('ad_id')}"
                title = f"Ad {r.get('ad_id')}"
            elif level == 'keyword':
                entity_id_raw = f"kw:{r.get('text')}|{r.get('match_type')}"
                title = r.get('text')
            else:
                continue
            entity_id = hash_text(entity_id_raw)
            text = _build_text(level, r)
            meta = {"level": level, "period": report.get(
                'period'), "customer_id": customer_id}
            ids = upsert_embeddings_for_entity(
                entity_type=level,
                entity_id=entity_id,
                scope_id=customer_id,
                title=title,
                text=text,
                model=model,
                meta=meta,
                db=db,
            )
            if ids:
                inserted += 1
                if len(sample_ids) < 10:
                    sample_ids.extend(ids)
            else:
                skipped += 1
        db.commit()
    finally:
        db.close()
    return {"ok": True, "level": level, "inserted": inserted, "skipped": skipped, "total_rows": len(report.get('rows', [])), "sample_ids": sample_ids, "period": report.get('period')}


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill embeddings for Google Ads entities")
    parser.add_argument('--customer', required=True,
                        help='Google Ads customer ID')
    parser.add_argument('--levels', nargs='*', default=[],
                        help='Entity levels to embed: campaign ad_group ad keyword')
    parser.add_argument('--search-terms', action='store_true',
                        help='Also embed recent search terms')
    parser.add_argument('--days', type=int, default=30,
                        help='Search terms lookback days (for --search-terms)')
    parser.add_argument('--limit', type=int, default=None,
                        help='Row limit per level (debugging)')
    parser.add_argument('--model', default=None,
                        help='Embedding model override')
    args = parser.parse_args(argv)

    levels = [l.lower() for l in args.levels if l]
    unsupported = [l for l in levels if l not in {
        'campaign', 'ad_group', 'ad', 'keyword'}]
    if unsupported:
        print(
            f"ERROR: Unsupported levels: {', '.join(unsupported)}", file=sys.stderr)
        return 2
    if not levels and not args.search_terms:
        print("ERROR: Provide --levels or --search-terms", file=sys.stderr)
        return 2

    overall: Dict[str, Any] = {"customer_id": args.customer, "results": []}

    # Process levels
    for level in levels:
        res = _embed_level(args.customer, level, args.model, args.limit)
        overall['results'].append(res)
        if not res.get('ok'):
            print(f"ERROR level {level}: {res.get('error')}", file=sys.stderr)
            return 3

    # Search terms
    if args.search_terms:
        db = SessionLocal()
        try:
            st = backfill_search_terms_for_customer(
                customer_id=args.customer, days=args.days, model=args.model, db=db, limit=args.limit)
        finally:
            db.close()
        overall['search_terms'] = st
        if not st.get('ok'):
            print(f"ERROR search_terms: {st.get('error')}", file=sys.stderr)
            return 3

    # Print summary
    print("Embedding backfill summary:")
    for r in overall.get('results', []):
        print(f" - {r.get('level')}: inserted {r.get('inserted')} skipped {r.get('skipped')} total_source_rows {r.get('total_rows')} period {r.get('period')}")
    if 'search_terms' in overall:
        st = overall['search_terms']
        print(
            f" - search_terms: inserted {st.get('inserted')} skipped {st.get('skipped')} total_source_rows {st.get('total_rows')} period {st.get('period')}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
