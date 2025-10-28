import os
from pathlib import Path
import requests
from dotenv import load_dotenv

# --------------------------------------------------------------------
# Config
# --------------------------------------------------------------------
DEFAULT_SECRETS_DIR = Path(os.path.expandvars(r"%USERPROFILE%\Secrets\google_ads"))
DEFAULT_ENV_PATH = DEFAULT_SECRETS_DIR / ".env"
DEFAULT_CLIENT_JSON = DEFAULT_SECRETS_DIR / "google_oauth_client.json"

# --------------------------------------------------------------------
# Helper functions
# --------------------------------------------------------------------
def mask(value: str, keep=4) -> str:
    if not value:
        return "<missing>"
    return value[:keep] + "..." + value[-keep:]

def check_file(path: Path, desc: str):
    if path.exists():
        print(f"✅ {desc}: {path}")
    else:
        print(f"❌ {desc} missing at {path}")

def check_ngrok():
    try:
        res = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=2)
        data = res.json()
        tunnels = data.get("tunnels", [])
        if not tunnels:
            print("⚠️  ngrok not running (no tunnels found)")
        else:
            print("✅ ngrok active:")
            for t in tunnels:
                print(f"   - {t.get('public_url')} -> {t.get('config', {}).get('addr')}")
    except Exception:
        print("⚠️  ngrok not running or not reachable on port 4040")

def check_fastapi():
    try:
        res = requests.get("http://127.0.0.1:8000/health", timeout=2)
        if res.status_code == 200:
            print("✅ FastAPI server responding at /health")
        else:
            print(f"⚠️  FastAPI server returned {res.status_code}")
    except Exception:
        print("⚠️  FastAPI not running on port 8000")

# --------------------------------------------------------------------
# Main verification
# --------------------------------------------------------------------
print("\n🔍 Verifying environment setup...\n")

# 1) Check secrets folder & files
check_file(DEFAULT_SECRETS_DIR, "Secrets folder")
check_file(DEFAULT_ENV_PATH, ".env file")
check_file(DEFAULT_CLIENT_JSON, "google_oauth_client.json")

# 2) Load environment vars
if DEFAULT_ENV_PATH.exists():
    load_dotenv(DEFAULT_ENV_PATH, override=True)

print("\n🔑 Environment variables:")
print(f"  DASH_API_KEY:            {mask(os.getenv('DASH_API_KEY'))}")
print(f"  DEV_TOKEN:               {mask(os.getenv('GOOGLE_ADS_DEVELOPER_TOKEN'))}")
print(f"  CLIENT_ID:               {mask(os.getenv('GOOGLE_ADS_CLIENT_ID'))}")
print(f"  CLIENT_SECRET:           {mask(os.getenv('GOOGLE_ADS_CLIENT_SECRET'))}")
print(f"  REFRESH_TOKEN:           {mask(os.getenv('GOOGLE_ADS_REFRESH_TOKEN'))}")
print(f"  LOGIN_CID:               {os.getenv('GOOGLE_ADS_LOGIN_CUSTOMER_ID')}")
print(f"  FASTAPI_GOOGLEADS_ENV:   {os.getenv('FASTAPI_GOOGLEADS_ENV')}")
print(f"  GOOGLE_OAUTH_CLIENT_JSON:{os.getenv('GOOGLE_OAUTH_CLIENT_JSON')}")

# 3) Check ngrok & FastAPI
print("\n🌐 Service checks:")
check_ngrok()
check_fastapi()

print("\n✅ Verification complete.\n")
