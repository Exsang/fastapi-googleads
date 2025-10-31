# scripts/env_check.py
import os
from pathlib import Path

# Load .env if present
try:
    from dotenv import load_dotenv  # type: ignore
    if Path(".env").exists():
        load_dotenv(".env", override=True)
except Exception:
    pass

required = [
    "GOOGLE_ADS_DEVELOPER_TOKEN",
    "GOOGLE_ADS_CLIENT_ID",
    "GOOGLE_ADS_CLIENT_SECRET",
    "GOOGLE_ADS_REFRESH_TOKEN",
]
missing = [k for k in required if not os.getenv(k)]

# Accept LOGIN_CUSTOMER_ID or DEFAULT_MCC_ID
login_cid = os.getenv("LOGIN_CUSTOMER_ID") or os.getenv("DEFAULT_MCC_ID")
if not login_cid:
    missing.append("LOGIN_CUSTOMER_ID (or DEFAULT_MCC_ID)")

if missing:
    print("[WARN] Missing:", ", ".join(missing))
else:
    print("[OK] All required Google Ads env vars present.")
