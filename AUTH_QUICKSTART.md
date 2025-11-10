# Authentication Quick Start

## Secure Access to All Endpoints

This FastAPI server uses **API key authentication** with browser-friendly cookie-based sessions for secure, persistent access to all endpoints.

---

## How to Authenticate (3 Ways)

### 1. **Browser Quick Login** (Recommended for Development)

1. **Start the server:**
   ```bash
   make dev
   # or
   uvicorn app.main:APP --reload
   ```

2. **Open your browser** and navigate to:
   ```
   http://127.0.0.1:8000/
   ```
   or (in Codespaces):
   ```
   https://<your-codespace-url>/
   ```

3. **You'll see the login page** showing:
   - ✅ Current authentication status
   - 🔐 **Quick Dev Login** button (in dev environments)
   - 📊 Links to dashboard and API docs

4. **Click "Authenticate Now"** to set a secure cookie (valid 24 hours)

5. **You're done!** All subsequent requests in your browser will include the auth cookie automatically.

---

### 2. **API Requests with Header** (Recommended for Scripts/cURL)

For programmatic access (scripts, Postman, cURL), send the API key via the `X-API-Key` header:

```bash
curl -H "X-API-Key: $DASH_API_KEY" \
  "http://127.0.0.1:8000/ads/report-ytd?customer_id=7414394764"
```

**Python example:**
```python
import os, requests

API_KEY = os.getenv("DASH_API_KEY")
BASE_URL = "http://127.0.0.1:8000"

headers = {"X-API-Key": API_KEY}
response = requests.get(f"{BASE_URL}/ads/customers", headers=headers)
print(response.json())
```

---

### 3. **One-Time Query Parameter** (Browser Convenience)

You can append `?key=<your-api-key>` to any protected URL **once**. The server will set the auth cookie automatically:

```
http://127.0.0.1:8000/ads/report-ytd?customer_id=7414394764&key=YOUR_API_KEY_HERE
```

After the first request, the cookie persists for 24 hours—no need to include `?key=...` again.

---

## Environment Setup

### Required: Set `DASH_API_KEY` in `.env`

Add this to your `.env` file at the repo root:

```bash
DASH_API_KEY=your-secret-api-key-here
```

**For Codespaces**, set it as a **repository secret** or **user secret**:
- Go to: Settings → Secrets → Codespaces
- Add `DASH_API_KEY` with your chosen value

---

## Session Management

- **Cookie name:** `dash_auth`
- **Duration:** 24 hours
- **Secure flags:** `HttpOnly`, `SameSite=Lax` (auto-upgrades to `Secure` in HTTPS)
- **Logout:** Clear cookies in your browser or wait 24h for expiration

---

## Key Routes

| Route | Purpose |
|-------|---------|
| `/` | Redirects to login page |
| `/login-page` | Browser-friendly login interface (shows auth status) |
| `/login?key=...` | Programmatic login endpoint (sets cookie, redirects to dashboard) |
| `/misc/dashboard` | Main dashboard with stats and endpoint links |
| `/docs` | Interactive Swagger UI (test endpoints live) |
| `/health` | Public health check (no auth required) |

---

## Testing Authentication

### Verify from Terminal

```bash
# 1. Load your .env
source .env

# 2. Test health (public, no auth)
curl http://127.0.0.1:8000/health

# 3. Test protected endpoint
curl -H "X-API-Key: $DASH_API_KEY" \
  http://127.0.0.1:8000/ads/customers
```

### Run Smoke Tests

The included smoke script tests /health and /ads/report-ytd with proper auth:

```bash
python scripts/smoke.py
```

---

## Troubleshooting

### "Invalid API key" (401)

**Cause:** Missing or incorrect `X-API-Key` header (or expired/missing cookie).

**Fix:**
1. Ensure `DASH_API_KEY` is set in `.env`
2. Restart the server: `make dev`
3. Re-authenticate via `/login-page` or include the header in requests

### "DASH_API_KEY not set; auth disabled"

**Cause:** The environment variable is missing.

**Fix:** Add `DASH_API_KEY=...` to `.env` and restart.

### Cookie not persisting in Codespaces

**Cause:** Browser blocking third-party cookies or mixed HTTP/HTTPS.

**Fix:**
1. Use the Codespaces public URL (not localhost forwarding)
2. Ensure `COOKIE_SECURE=1` if using HTTPS
3. Check browser settings allow cookies for the domain

---

## Security Best Practices

1. **Use strong API keys** (20+ random characters)
2. **Rotate keys periodically** (update `.env` and Codespaces secrets)
3. **Never commit `.env`** to version control (already gitignored)
4. **Enable HTTPS in production** and set `COOKIE_SECURE=1`
5. **Restrict CORS origins** in production (see `app/main.py` CORS config)

---

## Next Steps

Once authenticated:
- 📊 Visit `/misc/dashboard` for a visual interface with all endpoints
- 📖 Explore `/docs` (Swagger UI) to test endpoints interactively
- 🔍 Check `/ads/customers` to verify Google Ads API connectivity
- 📈 Run reports: `/ads/report-ytd`, `/ads/report-30d`

**Enjoy secure, seamless access to all your Google Ads data!** 🚀
