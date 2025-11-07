from __future__ import annotations

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from pathlib import Path
from urllib.parse import urlunsplit
import re
import json
import os

from ..deps.auth import require_auth
from ..settings import settings, DEFAULT_MCC_ID
from ..services.oauth import read_refresh_token
from ..services.usage_log import dashboard_stats

# All endpoints under /misc/*
router = APIRouter(prefix="/misc", tags=["misc"])


# ---------- helpers ----------
def _external_base(request: Request) -> str:
    """
    Compute the external base URL with this precedence:
      1) settings.PUBLIC_BASE_URL (explicit override)
      2) X-Forwarded-* headers (behind proxies)
      3) request.base_url (last resort)
    """
    if settings.PUBLIC_BASE_URL:
        return settings.PUBLIC_BASE_URL.rstrip("/")

    h = request.headers
    proto = (h.get("x-forwarded-proto") or h.get("x-scheme") or request.url.scheme or "http").split(",")[0].strip()
    host  = (h.get("x-forwarded-host")  or h.get("host")       or (request.url.hostname or "localhost")).split(",")[0].strip()
    port  = (h.get("x-forwarded-port")  or "").split(",")[0].strip()
    pref  = (h.get("x-forwarded-prefix") or "").split(",")[0].strip()

    if port and (":" not in host) and not ((proto == "http" and port == "80") or (proto == "https" and port == "443")):
        host = f"{host}:{port}"

    if pref and not pref.startswith("/"):
        pref = "/" + pref

    return urlunsplit((proto, host, pref, "", "")).rstrip("/")


# ---------------------------
# Basic health
# ---------------------------
@router.get("/health")
def health():
    key_status = "enabled" if os.getenv("DASH_API_KEY") else "disabled"
    return {
        "ok": True,
        "auth": key_status,
        "has_refresh_token": bool(read_refresh_token()),
        "login_customer_id": os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID") or None,
    }


# ---------------------------
# ENV (masked) — diagnostics
# ---------------------------
@router.get("/env", include_in_schema=False)
def show_env():
    """Diagnostic route to verify Codespaces secrets and env values (masked)."""
    keys = [
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
        "LOGIN_CUSTOMER_ID",
        "PUBLIC_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "DASH_API_KEY",
    ]
    result = {}
    for k in keys:
        val = os.getenv(k, "")
        if val:
            if len(val) > 12:
                val = val[:6] + "..." + val[-4:]
        result[k] = val or "<unset>"
    return result


# ---------------------------
# Home dashboard (secured)
# ---------------------------
from fastapi.responses import RedirectResponse

@router.get("/", include_in_schema=False)
async def misc_root():
    return RedirectResponse(url="/misc/dashboard", status_code=303)

def home(request: Request):
    base = _external_base(request)  # dynamic external base
    stats = dashboard_stats(DEFAULT_MCC_ID)

    def fmt(n):
        return "—" if n is None else f"{n:,}"

    get_cap = settings.BASIC_DAILY_GET_REQUEST_LIMIT
    ops_cap = settings.BASIC_DAILY_OPERATION_LIMIT

    rem_gets = max(get_cap - stats.get("today_get_requests", 0), 0)
    rem_ops = max(ops_cap - stats.get("today_operations", 0), 0)

    # Compact stat cards
    stat_cards = f"""
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <div class="text-sm text-slate-500">API calls (today)</div>
          <div class="mt-1 text-2xl font-semibold">{fmt(stats.get('today_usage_rows'))}</div>
        </div>
        <div class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <div class="text-sm text-slate-500">API calls (all time)</div>
          <div class="mt-1 text-2xl font-semibold">{fmt(stats.get('total_usage_rows'))}</div>
        </div>
        <div class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <div class="text-sm text-slate-500">GET requests (today)</div>
          <div class="mt-1 text-2xl font-semibold">{fmt(stats.get('today_get_requests'))}</div>
          <div class="text-xs text-slate-500 mt-1">Cap: {get_cap:,} • Remaining: {rem_gets:,}</div>
        </div>
        <div class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <div class="text-sm text-slate-500">Operations (today)</div>
          <div class="mt-1 text-2xl font-semibold">{fmt(stats.get('today_operations'))}</div>
          <div class="text-xs text-slate-500 mt-1">Cap: {ops_cap:,} • Remaining: {rem_ops:,}</div>
        </div>
      </div>
    """

    pages = {
        "OAuth & Authentication": [
            ("Start OAuth flow", f"{base}/auth/start"),
            ("OAuth callback (for reference)", f"{base}/auth/callback"),
        ],
        "Account & Ads Endpoints": [
            ("List accessible customers", f"{base}/ads/customers"),
            ("List example report", f"{base}/ads/example-report?customer_id={DEFAULT_MCC_ID}"),
            ("List active accounts under MCC", f"{base}/ads/active-accounts?mcc_id={DEFAULT_MCC_ID}"),
            ("30-day report", f"{base}/ads/report-30d?customer_id={DEFAULT_MCC_ID}"),
            ("YTD report", f"{base}/ads/report-ytd?customer_id={DEFAULT_MCC_ID}"),
            ("Keyword ideas", f"{base}/ads/keyword-ideas?customer_id={DEFAULT_MCC_ID}&seed=example"),
        ],
        "Usage & Debug": [
            ("View API usage log", f"{base}/ads/usage-log"),
            ("View API usage summary", f"{base}/ads/usage-summary"),
            ("View masked env (Codespaces)", f"{base}/misc/env"),
            ("ENVIRONMENT.md info", f"{base}/misc/debug/env-file"),
            ("ENVIRONMENT.md summary (JSON)", f"{base}/misc/env-summary"),
            ("All routes (auto-list)", f"{base}/misc/_routes"),
        ],
        "Docs": [
            ("Interactive Swagger UI", f"{base}/docs"),
            ("ReDoc (alternative API docs)", f"{base}/redoc"),
        ],
    }

    def render_section(title, links):
        links_html = "".join(
            f'''
            <a href="{href}" target="_blank"
               class="inline-flex items-center justify-between w-full rounded-lg border border-slate-200 bg-white hover:bg-slate-50 px-3 py-2 text-sm transition">
              <span class="truncate">{text}</span>
              <span aria-hidden="true" class="ml-3 text-slate-400">›</span>
            </a>
            '''
            for text, href in links
        )
        return f"""
        <section class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <h2 class="text-base font-semibold mb-3">{title}</h2>
          <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-2">
            {links_html}
          </div>
        </section>
        """

    body = "".join(render_section(title, links) for title, links in pages.items())

    html = f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Google Ads API Gateway</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-50 text-slate-900">
  <div class="max-w-7xl mx-auto p-6 space-y-8">
    <header>
      <h1 class="text-3xl font-bold tracking-tight">Google Ads API Gateway</h1>
      <p class="text-slate-600 mt-1">Live stats and quick links to your endpoints.</p>
      <div class="mt-2 text-sm text-slate-500">
        <span class="font-semibold">Base:</span> {base} &nbsp;•&nbsp;
        <span class="font-semibold">Default MCC:</span> {DEFAULT_MCC_ID}
      </div>
      <div class="text-xs text-slate-500 mt-1">Note: Remaining values are estimates from local logs. The API Center in Google Ads is the source of truth.</div>
    </header>

    {stat_cards}

    <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
      {body}
    </div>

    <footer class="text-xs text-slate-500 pt-6 border-t border-slate-200">
      <p>© 2025 FastAPI Google Ads Gateway • Built with FastAPI + TailwindCSS</p>
    </footer>
  </div>
</body>
</html>
"""
    return HTMLResponse(html)


# ---------------------------
# Routes listing (secured)
# ---------------------------
@router.get("/_routes", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
def list_routes(request: Request):
    from fastapi.routing import APIRoute
    base = _external_base(request)
    rows = []
    for route in request.app.routes:
        if isinstance(route, APIRoute):
            methods = ", ".join(sorted(m for m in route.methods if m in {"GET", "POST", "PUT", "DELETE", "PATCH"}))
            path = route.path
            needs_params = "{" in path and "}" in path
            href = None if needs_params else f"{base}{path}"
            rows.append((methods, path, href))
    rows.sort(key=lambda r: r[1])
    html = [
        "<!doctype html><html><head><meta charset='utf-8'><title>Routes</title>",
        "<style>body{font-family:sans-serif;padding:20px}table{border-collapse:collapse;width:100%}th,td{padding:8px;border-bottom:1px solid #eee}a{color:#2563eb;text-decoration:none}a:hover{text-decoration:underline}</style>",
        "</head><body><h1>Available Routes</h1><table><tr><th>Method(s)</th><th>Path</th><th>Link</th></tr>",
    ]
    for methods, path, href in rows:
        link = f'<a href="{href}" target="_blank">{href}</a>' if href else "<span style='color:#888'>params required</span>"
        html.append(f"<tr><td>{methods}</td><td><code>{path}</code></td><td>{link}</td></tr>")
    html.append("</table></body></html>")
    return HTMLResponse("".join(html))


# ---------------------------
# Debug env (safe preview)
# ---------------------------
@router.get("/debug/env")
def debug_env():
    """Preview core runtime env/config info (safe to print)."""
    dt = settings.GOOGLE_ADS_DEVELOPER_TOKEN
    login = os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID")
    return {
        "dev_token_preview": f"{dt[:6]}...{dt[-4:]}" if dt else None,
        "login_customer_id": login or None,
        "get_cap": settings.BASIC_DAILY_GET_REQUEST_LIMIT,
        "ops_cap": settings.BASIC_DAILY_OPERATION_LIMIT,
        "source": "env (Codespaces secrets preferred)",
    }


# ---------------------------
# ENVIRONMENT.md metadata
# ---------------------------
@router.get("/debug/env-file")
def debug_env_file():
    """Quick metadata about ENVIRONMENT.md (canonical source of truth)."""
    p = Path(__file__).resolve().parents[2] / "ENVIRONMENT.md"
    exists = p.exists()
    size = p.stat().st_size if exists else 0
    return {"ok": exists, "path": str(p), "size_bytes": size}


# ---------------------------
# ENVIRONMENT.md summary as JSON (secured)
# ---------------------------
@router.get("/env-summary", dependencies=[Depends(require_auth)])
def env_summary():
    """
    Parse ENVIRONMENT.md auto-generated block and return a structured JSON summary.
    """
    p = Path(__file__).resolve().parents[2] / "ENVIRONMENT.md"
    if not p.exists():
        raise HTTPException(status_code=404, detail="ENVIRONMENT.md not found at repo root.")

    md = p.read_text(encoding="utf-8")
    start = "<!-- BEGIN AUTO -->"
    end = "<!-- END AUTO -->"
    i = md.find(start)
    j = md.find(end)
    if i == -1 or j == -1 or j <= i:
        raise HTTPException(status_code=422, detail="Auto-generated section not found in ENVIRONMENT.md.")

    block = md[i + len(start): j].strip()

    # 1) Header line: "_Generated at: **TIMESTAMP**  |  **BRANCH@COMMIT**_"
    header_re = re.compile(r"_Generated at:\s+\*\*(.+?)\*\*\s+\|\s+\*\*(.+?)\*\*_")
    header_m = header_re.search(block)
    generated_at = header_m.group(1) if header_m else None
    git_tag = header_m.group(2) if header_m else None

    # Optional counts line
    counts_re = re.compile(r"\*\*Routes:\*\*\s*(\d+).*\*\*Namespaces:\*\*\s*([^\n]+)")
    counts_m = counts_re.search(block)
    routes_count = int(counts_m.group(1)) if counts_m else None
    namespaces = [s.strip() for s in counts_m.group(2).split(",")] if counts_m else []

    # Routes table
    routes_section_re = re.compile(r"### Routes \(live\)\s*\n(.*?)\n\n###", re.DOTALL)
    routes_sec = routes_section_re.search(block)
    routes = []
    if routes_sec:
        table = routes_sec.group(1).strip().splitlines()
        for line in table:
            if not line.startswith("|") or line.startswith("|---"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 3 and cells[0] != "Method(s)":
                method_s, path_md, name = cells[0], cells[1], cells[2]
                path = path_md.strip().strip("`")
                methods = [m.strip() for m in method_s.split(",") if m.strip()]
                routes.append({"methods": methods, "path": path, "name": name})

    # Settings & Versions
    def extract_json_block(title: str):
        rgx = re.compile(rf"### {re.escape(title)}\s*\n```(.*?)```", re.DOTALL)
        m = rgx.search(block)
        if not m:
            return None
        raw = m.group(1).strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    # NOTE: pass the literal title; re.escape() handles parentheses safely.
    settings_json = extract_json_block("Settings snapshot (selected)")
    versions = extract_json_block("Package versions")

    # Folder tree
    tree_re = re.compile(r"### Folder tree \(depth 2\)\s*\n```(.*?)```", re.DOTALL)
    tree_m = tree_re.search(block)
    folder_tree = tree_m.group(1).strip() if tree_m else None

    return {
        "generated_at": generated_at,
        "git": git_tag,
        "routes_count": routes_count if routes_count is not None else len(routes),
        "namespaces": namespaces,
        "routes": routes,
        "settings": settings_json,
        "versions": versions,
        "folder_tree": folder_tree,
    }

# --- add (or ensure) these imports exist near the top ---
from fastapi import Request
from fastapi.responses import HTMLResponse
import os
import html

# --- add this NEW endpoint ---
@router.get("/dashboard", response_class=HTMLResponse)
async def misc_dashboard(request: Request):
    """
    Minimal HTML dashboard that:
      - Accepts Authorization header OR ?key=<DASH_API_KEY>
      - Shows health, usage, and customers count
      - Uses fetch() to call your own API endpoints
    """
    dash_key = os.environ.get("DASH_API_KEY")
    if not dash_key:
        return HTMLResponse("<h3>Server missing DASH_API_KEY</h3>", status_code=500)

    # Accept either header bearer token or ?key= token
    header = request.headers.get("authorization") or request.headers.get("Authorization")
    query_key = request.query_params.get("key")
    client_token = None
    if header and header.lower().startswith("bearer "):
        client_token = header.split(" ", 1)[1].strip()
    elif query_key:
        client_token = query_key.strip()

    # Render HTML; JS will attach the token and fetch stats
    # (show a subtle warning if no token was provided)
    warn = "" if client_token else "<em>Provide ?key=… or use Authorization header to load protected stats.</em>"

    # Escape token in HTML just to be safe (we only stash it in JS)
    safe_token = html.escape(client_token or "")

    return HTMLResponse(f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Customer Dashboard</title>
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <style>
    :root {{
      --bg:#0b1220; --fg:#e6edf3; --muted:#94a3b8; --card:#111827; --border:#1f2937; --accent:#93c5fd;
    }}
    body {{ margin:0; background:var(--bg); color:var(--fg); font-family: ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial; }}
    .topbar {{ display:flex; gap:8px; flex-wrap:wrap; align-items:center; padding:12px 16px; border-bottom:1px solid var(--border); background:#0f172a; }}
    .chip {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:6px 10px; }}
    .chip b {{ color:var(--accent); }}
    .wrap {{ max-width:1100px; margin:20px auto; padding:0 16px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:16px; }}
    .card {{ background:var(--card); border:1px solid var(--border); border-radius:14px; padding:14px; }}
    input[type=text] {{ width:320px; background:var(--bg); color:var(--fg); border:1px solid var(--border); border-radius:10px; padding:6px 8px; }}
    button {{ background:var(--card); color:var(--fg); border:1px solid var(--border); border-radius:10px; padding:6px 10px; cursor:pointer; }}
    a, a:visited {{ color:var(--accent); text-decoration:none; }}
  </style>
</head>
<body>
  <div class="topbar">
    <div class="chip">📦 <b id="appTitle">Google API Backend</b></div>
    <div class="chip">🩺 Health: <b id="healthVal">…</b></div>
    <div class="chip">📈 24h Usage: <b id="usageVal">—</b></div>
    <div class="chip">👥 Customers: <b id="custVal">—</b></div>
    <span style="flex:1"></span>
    <input id="apiKey" type="text" placeholder="Paste DASH_API_KEY…" />
    <button id="saveKey">Use key</button>
  </div>

  <div class="wrap">
    <div class="grid">
      <div class="card">
        <h3 style="margin:6px 0 8px">Quick Links</h3>
        <ul style="margin:0; padding-left:18px; line-height:1.8">
          <li><a href="/docs" target="_blank">Swagger UI</a></li>
          <li><a href="/misc/env-summary" target="_blank">Env Summary</a></li>
          <li><a href="/ops/fs?path=&depth=2" target="_blank">Repo Browser (JSON)</a></li>
        </ul>
        <p style="color:var(--muted); margin-top:10px;">{warn}</p>
      </div>

      <div class="card">
        <h3 style="margin:6px 0 8px">Notes</h3>
        <p style="color:var(--muted);">This page pulls data from:</p>
        <ul style="margin:0; padding-left:18px; line-height:1.8; color:var(--muted);">
          <li><code>/health</code> (no auth)</li>
          <li><code>/usage/summary</code> (requires API key)</li>
          <li><code>/ads/customers</code> (requires API key)</li>
        </ul>
      </div>
    </div>
  </div>

  <script>
    // Prefer key from URL (?key=...), then localStorage, then server-injected
    const url = new URL(window.location.href);
    const qpKey = url.searchParams.get('key') || '';
    const lsKey = window.localStorage.getItem('DASH_API_KEY') || '';
    const injected = "{safe_token}";
    const token = qpKey || injected || lsKey;

    // Populate input if present
    const input = document.getElementById('apiKey');
    if (input) input.value = token || '';

    // Save button
    const btn = document.getElementById('saveKey');
    if (btn) btn.addEventListener('click', () => {{
      const val = (document.getElementById('apiKey').value || '').trim();
      if (val) {{
        window.localStorage.setItem('DASH_API_KEY', val);
        location.href = window.location.pathname + '?key=' + encodeURIComponent(val);
      }}
    }});

    // Simple GET helper that adds Authorization header if token exists
    async function getJSON(path) {{
      const headers = token ? {{ 'Authorization': 'Bearer ' + token }} : {{}};
      const res = await fetch(path, {{ headers }});
      if (!res.ok) throw new Error('HTTP ' + res.status + ' for ' + path);
      return res.json();
    }}

    // Load Health
    getJSON('/health').then(d => {{
      document.getElementById('healthVal').textContent = (d && d.status) || 'ok';
    }}).catch(_ => {{
      document.getElementById('healthVal').textContent = 'error';
    }});

    // Load Usage
    getJSON('/usage/summary').then(d => {{
      const v = d.requests_24h ?? d.requests ?? JSON.stringify(d);
      document.getElementById('usageVal').textContent = v;
    }}).catch(_ => {{
      document.getElementById('usageVal').textContent = 'unauth';
    }});

    // Load Customers count
    getJSON('/ads/customers').then(d => {{
      const n = Array.isArray(d) ? d.length : (d.customers?.length || 0);
      document.getElementById('custVal').textContent = n;
    }}).catch(_ => {{
      document.getElementById('custVal').textContent = 'unauth';
    }});
  </script>
</body>
</html>""")
