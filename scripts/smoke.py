# scripts/smoke.py
import os
import sys
from pathlib import Path

# Load .env if present
try:
    from dotenv import load_dotenv  # type: ignore
    if Path(".env").exists():
        load_dotenv(".env", override=True)
except Exception:
    pass

from google.ads.googleads.client import GoogleAdsClient
import json
import time

login_cid = os.getenv("LOGIN_CUSTOMER_ID") or os.getenv("DEFAULT_MCC_ID")
required = [
    "GOOGLE_ADS_DEVELOPER_TOKEN",
    "GOOGLE_ADS_CLIENT_ID",
    "GOOGLE_ADS_CLIENT_SECRET",
    "GOOGLE_ADS_REFRESH_TOKEN",
]
missing = [k for k in required if not os.getenv(k)]
if not login_cid:
    missing.append("LOGIN_CUSTOMER_ID (or DEFAULT_MCC_ID)")
if missing:
    print(f"[WARN] Missing required env vars: {', '.join(missing)}")
    sys.exit(1)

cfg = {
    "developer_token": os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN"),
    "login_customer_id": login_cid,
    "client_id": os.getenv("GOOGLE_ADS_CLIENT_ID"),
    "client_secret": os.getenv("GOOGLE_ADS_CLIENT_SECRET"),
    "refresh_token": os.getenv("GOOGLE_ADS_REFRESH_TOKEN"),
    "use_proto_plus": True,
}
c = GoogleAdsClient.load_from_dict(cfg)
svc = c.get_service("CustomerService")
print(list(svc.list_accessible_customers().resource_names))

# ------------------------------------------------------------------
# HTTP smoke checks for FastAPI endpoints (health + YTD report)
# ------------------------------------------------------------------
try:
    import requests  # type: ignore
except Exception:
    print("[WARN] requests not installed; skipping HTTP endpoint smoke tests.")
    sys.exit(0)

BASE = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
API_KEY = os.getenv("DASH_API_KEY")
CID = os.getenv("YTD_CUSTOMER_ID") or login_cid


def _head(url: str):
    try:
        r = requests.get(url, timeout=5)
        return r.status_code, r.text[:300], r.headers
    except Exception as e:
        return None, str(e), {}


def check_health():
    sc, body, _ = _head(f"{BASE}/health")
    print(f"/health -> {sc} {body}")


def check_ytd():
    if not API_KEY:
        print("[WARN] DASH_API_KEY not set; skipping protected /ads/report-ytd call.")
        return
    # breakdown defaults to customer
    url = f"{BASE}/ads/report-ytd?customer_id={CID}"
    try:
        r = requests.get(url, headers={"X-API-Key": API_KEY}, timeout=15)
    except Exception as e:
        print(f"/ads/report-ytd request failed: {e}")
        return
    print(f"/ads/report-ytd -> {r.status_code}")
    try:
        j = r.json()
    except Exception:
        print("  (non-JSON response)")
        print(r.text[:500])
        return
    if isinstance(j, dict) and j.get("ok") and isinstance(j.get("rows"), list):
        rows = j["rows"]
        print(f"  rows: {len(rows)} (showing up to 3)")
        for sample in rows[:3]:
            print("   -", json.dumps(sample))
    else:
        print("  response:", json.dumps(j)[:800])


print("[SMOKE] HTTP endpoint checks starting...")
check_health()
check_ytd()
