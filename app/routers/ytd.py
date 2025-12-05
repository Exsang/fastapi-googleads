"""
DEPRECATED MODULE: app/routers/ytd.py

This router has been superseded by the consolidated endpoint:
  GET /ads/report-ytd-daily
implemented in app/routers/ads.py using run_ytd_daily_campaign_report().

The original persistence flow (ytd_repo) has been removed in favor of the
unified ETL pipeline under app/routers/etl.py and app/services/etl_google_ads.py.

This file is kept as a stub for compatibility and should not be imported.
"""

DEPRECATED = True
