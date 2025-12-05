"""
DEPRECATED MODULE: app/services/google_ads_reports.py

Replaced by run_ytd_daily_campaign_report() in app/services/google_ads.py which
uses the resilient search_stream() wrapper and returns normalized rows suitable
for JSON/CSV via /ads/report-ytd-daily.

Do not import this module in new code.
"""

DEPRECATED = True
