# scripts/smoke.py
import os, sys
from pathlib import Path

# Load .env if present
try:
    from dotenv import load_dotenv  # type: ignore
    if Path(".env").exists():
        load_dotenv(".env", override=True)
except Exception:
    pass

from google.ads.googleads.client import GoogleAdsClient

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
