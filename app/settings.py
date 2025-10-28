# app/settings.py
import os
from pathlib import Path

# --------------------------------------------------------------------
# App Metadata
# --------------------------------------------------------------------
APP_TITLE = "Google Ads API Gateway"

# --------------------------------------------------------------------
# Secrets and configuration
# --------------------------------------------------------------------

# Default external secrets directory
DEFAULT_SECRETS_DIR = os.path.expandvars(r"%USERPROFILE%\Secrets\google_ads")

# API key for your gateway
API_KEY = os.getenv("DASH_API_KEY", "")

# --------------------------------------------------------------------
# Google Ads / OAuth settings
# --------------------------------------------------------------------
DEFAULT_MCC_ID = os.getenv("DEFAULT_MCC_ID", "7414394764")
LOGIN_CID = (
    os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID")
    or os.getenv("LOGIN_CID")
    or DEFAULT_MCC_ID
)
DEV_TOKEN = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", "")

CLIENT_ID = os.getenv("GOOGLE_ADS_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("GOOGLE_ADS_CLIENT_SECRET", "")
REFRESH_TOKEN = os.getenv("GOOGLE_ADS_REFRESH_TOKEN", "")

# OAuth client JSON path
CLIENT_JSON_PATH = os.getenv(
    "GOOGLE_OAUTH_CLIENT_JSON",
    os.getenv("OAUTH_CLIENT_JSON_PATH", os.path.join(DEFAULT_SECRETS_DIR, "google_oauth_client.json")),
)

# Optional refresh token file (for backward compatibility)
REFRESH_TOKEN_PATH = Path(
    os.getenv("GOOGLE_ADS_REFRESH_TOKEN_FILE", os.path.join(DEFAULT_SECRETS_DIR, "_refresh_token.txt"))
)

# Redirect URI for OAuth flow
REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "http://127.0.0.1:8000/auth/callback")

# Scopes
SCOPES = ["https://www.googleapis.com/auth/adwords"]

# --------------------------------------------------------------------
# Usage caps (for dashboard or rate limiting)
# --------------------------------------------------------------------
GET_CAP = int(os.getenv("BASIC_DAILY_GET_REQUEST_LIMIT", "1000"))
OPS_CAP = int(os.getenv("BASIC_DAILY_OPERATION_LIMIT", "15000"))
