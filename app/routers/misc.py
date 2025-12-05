from __future__ import annotations
import html
from fastapi import Request
from fastapi.responses import RedirectResponse

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
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
    proto = (h.get("x-forwarded-proto") or h.get("x-scheme")
             or request.url.scheme or "http").split(",")[0].strip()
    host = (h.get("x-forwarded-host") or h.get("host")
            or (request.url.hostname or "localhost")).split(",")[0].strip()
    port = (h.get("x-forwarded-port") or "").split(",")[0].strip()
    pref = (h.get("x-forwarded-prefix") or "").split(",")[0].strip()

    if port and (":" not in host) and not ((proto == "http" and port == "80") or (proto == "https" and port == "443")):
        host = f"{host}:{port}"

    if pref and not pref.startswith("/"):
        pref = "/" + pref

    return urlunsplit((proto, host, pref, "", "")).rstrip("/")


# Reusable JavaScript snippet for CID input normalization & persistence.
# Served as a static-like asset to avoid duplication across dashboards.
CID_JS_SNIPPET = r"""// Shared CID helper (normalizes numeric ID & persists)
export function attachCID(el, opts={}) {
  const key = (opts.key || 'LAST_CID');
  function normCID(v){return (v||'').replace(/[^0-9]/g,'');}
  const saved = localStorage.getItem(key);
  if(saved && !el.value) el.value = saved;
  el.addEventListener('input', () => { const v = normCID(el.value); if(el.value !== v) el.value = v; });
  el.addEventListener('blur', () => { const v = normCID(el.value); if(v) localStorage.setItem(key, v); });
  el.addEventListener('keydown', e => { if(e.key==='Enter' && typeof opts.onEnter==='function'){ opts.onEnter(normCID(el.value)); }});
  return { get: () => normCID(el.value), set: v => { el.value = normCID(v); localStorage.setItem(key, normCID(v)); } };
}
"""


@router.get("/cid.js", response_class=PlainTextResponse, dependencies=[Depends(require_auth)])
async def shared_cid_js():
    """Serve a tiny ES module with a helper to attach CID behavior to an input.

    Import example:
      <script type='module'>
        import { attachCID } from '/misc/cid.js';
        const cidCtl = attachCID(document.getElementById('cidInput'), { onEnter: () => ask() });
        (function(){
          const _qs = new URLSearchParams(location.search); const _qcid = _qs.get('customer_id'); if(_qcid){ try { cidCtl.set(_qcid); } catch(e){} }
        })();
        function ask(){
          const question = document.getElementById('question').value.trim();
          const cid = cidCtl.get();
          if(!question){ return; }
          fetch(`/assist/answer?question=${encodeURIComponent(question)}${cid?`&customer_id=${cid}`:''}`)
            .then(r=>r.json())
            .then(data => {
              const out = document.getElementById('answer');
              out.innerHTML = `<h3>Answer</h3><pre>${data.answer || '(no answer)'}\n\nContexts:\n${(data.contexts||[]).map(c=>c.text).join('\n---\n')}</pre>`;
            })
            .catch(err => console.error(err));
        }
        document.getElementById('askBtn').addEventListener('click', ask);
      </script>
        <script>
          (function(){
            const _qs = new URLSearchParams(location.search); const _qcid = _qs.get('customer_id'); if(_qcid){ try { cid.set(_qcid); } catch(e){} }
          })();
        </script>
      <script>
        (function(){
          const _qs = new URLSearchParams(location.search); const _qcid = _qs.get('customer_id'); if(_qcid){ try { cid.set(_qcid); } catch(e){} }
        })();
      </script>
    """
    return PlainTextResponse(CID_JS_SNIPPET, media_type="text/javascript")


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
        # Customer/ID dependent analytics & reports (pre-filled with default MCC where useful)
        "Analytics & Reporting (CID scoped)": [
            ("Example campaign list",
             f"{base}/ads/example-report?customer_id={DEFAULT_MCC_ID}"),
            ("Active accounts under MCC",
             f"{base}/ads/active-accounts?mcc_id={DEFAULT_MCC_ID}"),
            ("30-day campaign performance",
             f"{base}/ads/report-30d?customer_id={DEFAULT_MCC_ID}"),
            ("Year-to-date performance",
             f"{base}/ads/report-ytd?customer_id={DEFAULT_MCC_ID}"),
            ("MTD dashboard (UI)",
                f"{base}/misc/analytics-mtd"),
            ("YTD daily dashboard (UI)",
                f"{base}/misc/analytics-ytd-daily"),
            ("Keyword Ideas dashboard (UI)",
                f"{base}/misc/analytics-keyword-ideas"),
            ("Keyword ideas (seed=example)",
             f"{base}/ads/keyword-ideas?customer_id={DEFAULT_MCC_ID}&seed=example"),
            ("Month-to-date (campaign)",
             f"{base}/ads/report-mtd?customer_id={DEFAULT_MCC_ID}&level=campaign"),
            ("Month-to-date (ad group)",
             f"{base}/ads/report-mtd?customer_id={DEFAULT_MCC_ID}&level=ad_group"),
            ("Month-to-date (ad)",
             f"{base}/ads/report-mtd?customer_id={DEFAULT_MCC_ID}&level=ad"),
            ("Month-to-date (keyword)",
             f"{base}/ads/report-mtd?customer_id={DEFAULT_MCC_ID}&level=keyword"),
            ("Launch multi-level analytics UI",
             f"{base}/misc/analytics?customer_id={DEFAULT_MCC_ID}"),
        ],
        # Non-CID dashboards & introspection (fast navigation)
        "Dashboards & Introspection (global)": [
            ("Core dashboard (this page)", f"{base}/misc/dashboard"),
            ("Health (JSON)", f"{base}/misc/health"),
            ("Quota usage summary", f"{base}/ads/quota-summary"),
            ("API usage log (CSV view)", f"{base}/ads/usage-log"),
            ("API usage summary", f"{base}/ads/usage-summary"),
            ("All routes (HTML)", f"{base}/misc/_routes"),
            ("ENVIRONMENT.md summary (JSON)", f"{base}/misc/env-summary"),
            ("ENVIRONMENT.md file info", f"{base}/misc/debug/env-file"),
            ("Masked environment preview", f"{base}/misc/env"),
            ("Repo file system explorer", f"{base}/ops/fs?path=&depth=2"),
        ],
        "Docs": [
            ("Swagger UI", f"{base}/docs"),
            ("ReDoc alternative docs", f"{base}/redoc"),
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

    body = "".join(render_section(title, links)
                   for title, links in pages.items())

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
            methods = ", ".join(sorted(m for m in route.methods if m in {
                                "GET", "POST", "PUT", "DELETE", "PATCH"}))
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
        html.append(
            f"<tr><td>{methods}</td><td><code>{path}</code></td><td>{link}</td></tr>")
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
        raise HTTPException(
            status_code=404, detail="ENVIRONMENT.md not found at repo root.")

    md = p.read_text(encoding="utf-8")
    start = "<!-- BEGIN AUTO -->"
    end = "<!-- END AUTO -->"
    i = md.find(start)
    j = md.find(end)
    if i == -1 or j == -1 or j <= i:
        raise HTTPException(
            status_code=422, detail="Auto-generated section not found in ENVIRONMENT.md.")

    block = md[i + len(start): j].strip()

    # 1) Header line: "_Generated at: **TIMESTAMP**  |  **BRANCH@COMMIT**_"
    header_re = re.compile(
        r"_Generated at:\s+\*\*(.+?)\*\*\s+\|\s+\*\*(.+?)\*\*_")
    header_m = header_re.search(block)
    generated_at = header_m.group(1) if header_m else None
    git_tag = header_m.group(2) if header_m else None

    # Optional counts line
    counts_re = re.compile(
        r"\*\*Routes:\*\*\s*(\d+).*\*\*Namespaces:\*\*\s*([^\n]+)")
    counts_m = counts_re.search(block)
    routes_count = int(counts_m.group(1)) if counts_m else None
    namespaces = [s.strip()
                  for s in counts_m.group(2).split(",")] if counts_m else []

    # Routes table
    routes_section_re = re.compile(
        r"### Routes \(live\)\s*\n(.*?)\n\n###", re.DOTALL)
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
    tree_re = re.compile(
        r"### Folder tree \(depth 2\)\s*\n```(.*?)```", re.DOTALL)
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
    header = request.headers.get(
        "authorization") or request.headers.get("Authorization")
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
        <h3 style="margin:6px 0 8px">System Health & Env</h3>
        <ul style="margin:0; padding-left:18px; line-height:1.6; color:var(--muted)">
          <li><a href="/misc/dashboard" target="_blank">Core Dashboard</a></li>
          <li><a href="/misc/health" target="_blank">Health (JSON)</a></li>
          <li><a href="/misc/env" target="_blank">Masked Env Preview</a></li>
          <li><a href="/misc/env-summary" target="_blank">ENVIRONMENT.md Summary (JSON)</a></li>
          <li><a href="/misc/debug/env-file" target="_blank">ENVIRONMENT.md File Info</a></li>
        </ul>
        <p style="color:var(--muted); margin-top:10px; font-size:12px;">{warn}</p>
      </div>

      <div class="card">
        <h3 style="margin:6px 0 8px">Usage & Quota</h3>
        <ul style="margin:0; padding-left:18px; line-height:1.6; color:var(--muted)">
          <li><a href="/ads/usage-log" target="_blank">API Usage Log</a></li>
          <li><a href="/ads/usage-summary" target="_blank">API Usage Summary</a></li>
          <li><a href="/ads/quota-summary" target="_blank">Quota Usage Summary</a></li>
        </ul>
      </div>

      <div class="card">
        <h3 style="margin:6px 0 8px">Docs & Discovery</h3>
        <ul style="margin:0; padding-left:18px; line-height:1.6; color:var(--muted)">
          <li><a href="/docs" target="_blank">Swagger UI</a></li>
          <li><a href="/redoc" target="_blank">ReDoc Docs</a></li>
          <li><a href="/misc/_routes" target="_blank">All Routes (HTML)</a></li>
        </ul>
      </div>

      <div class="card">
        <h3 style="margin:6px 0 8px">Assist & Embeddings</h3>
        <ul style="margin:0; padding-left:18px; line-height:1.6; color:var(--muted)">
          <li><a href="/assist/search?format=html" target="_blank">Assist Search (HTML)</a></li>
          <li><a href="/misc/assist-console" target="_blank">Assist Answer Console</a></li>
          <li><a href="/misc/agents" target="_blank">Agents Proposals Console</a></li>
        </ul>
        <div style="margin-top:10px; padding:10px; border:1px dashed var(--border); border-radius:10px;">
          <div style="font-size:12px; color:var(--muted); margin-bottom:6px;">Re-embed stale vectors (manual trigger)</div>
          <div style="display:flex; flex-wrap:wrap; gap:8px; align-items:center;">
            <input id="reCid" type="text" placeholder="scope_id (CID) optional" style="width:200px;" />
            <input id="reType" type="text" placeholder="entity_type (optional)" style="width:200px;" />
            <input id="reMaxAge" type="number" placeholder="max_age_hours" value="24" style="width:140px;" />
            <input id="reLimit" type="number" placeholder="limit" value="150" style="width:120px;" />
            <label style="font-size:12px; color:var(--muted); display:inline-flex; align-items:center; gap:6px;"><input id="reForce" type="checkbox"/> force</label>
            <button id="reLoadCfg">Load config</button>
            <button id="reRun">Re-embed now</button>
          </div>
          <div id="reCfg" style="font-size:12px; color:var(--muted); margin-top:6px;">—</div>
          <div id="reOut" style="font-size:12px; color:var(--muted); margin-top:4px;">—</div>
        </div>
      </div>

      <div class="card">
        <h3 style="margin:6px 0 8px">Ads & ETL Shortcuts</h3>
        <div style="display:flex; gap:8px; align-items:center; margin-bottom:8px;">
          <input id="cidInput" type="text" placeholder="Enter Customer ID" style="flex:1; padding:6px 10px; border:1px solid #ccc; border-radius:6px; font-size:13px;" />
          <button id="cidConfirm" style="padding:6px 16px; background:#007bff; color:#fff; border:none; border-radius:6px; cursor:pointer; font-size:13px;">Confirm</button>
        </div>
        <p style="color:var(--muted); font-size:12px; margin:0;">Enter a Customer ID and click Confirm to open the shortcuts dashboard.</p>
        <script>
          document.getElementById('cidConfirm').addEventListener('click', () => {{
            const cid = document.getElementById('cidInput').value.trim().replace(/-/g, '');
            if(!cid){{ alert('Please enter a Customer ID'); return; }}
            window.open(`/misc/cid-dashboard?customer_id=${{cid}}`, '_blank');
          }});
          document.getElementById('cidInput').addEventListener('keypress', (e) => {{
            if(e.key === 'Enter'){{ document.getElementById('cidConfirm').click(); }}
          }});
        </script>
      </div>

      <div class="card">
        <h3 style="margin:6px 0 8px">Repository Tools</h3>
        <ul style="margin:0; padding-left:18px; line-height:1.6; color:var(--muted)">
          <li><a href="/ops/fs?path=&depth=2" target="_blank">Repo Browser (JSON)</a></li>
        </ul>
      </div>

      <div class="card">
        <h3 style="margin:6px 0 8px">Notes</h3>
        <p style="color:var(--muted);">This page pulls data from:</p>
        <ul style="margin:0; padding-left:18px; line-height:1.8; color:var(--muted);">
          <li><code>/health</code> (no auth)</li>
          <li><code>/ads/usage-summary</code> (requires API key)</li>
          <li><code>/ads/customers</code> (requires API key)</li>
        </ul>
      </div>

      <div class="card" style="grid-column: 1 / -1;">
        <h3 style="margin:6px 0 8px">Deep Analytics</h3>
        <p style="color:var(--muted); font-size:13px;">Launch a multi-level dashboard (campaign, ad group, ad, keyword) for a given Customer ID.</p>
        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-top:8px;">
          <input id="cidInput" type="text" placeholder="Enter Customer ID (e.g., 741-439-4764)" />
          <button id="openAnalytics">Open Analytics</button>
        </div>
        <div id="anStatus" style="color:var(--muted); font-size:12px; margin-top:6px;">—</div>
      </div>
    </div>
  </div>

  <script>
    const url = new URL(window.location.href);
    const qpKey = url.searchParams.get('key') || '';
    const lsKey = window.localStorage.getItem('DASH_API_KEY') || '';
    const injected = "{safe_token}";
    const token = qpKey || injected || lsKey;

    const input = document.getElementById('apiKey');
    if (input) input.value = token || '';

    const btn = document.getElementById('saveKey');
    if (btn) btn.addEventListener('click', () => {{
      const val = (document.getElementById('apiKey').value || '').trim();
      if (val) {{
        window.localStorage.setItem('DASH_API_KEY', val);
        location.href = window.location.pathname + '?key=' + encodeURIComponent(val);
      }}
    }});

    async function getJSON(path) {{
      const headers = token ? {{ 'Authorization': 'Bearer ' + token }} : {{}};
      const res = await fetch(path, {{ headers }});
      if (!res.ok) throw new Error('HTTP ' + res.status + ' for ' + path);
      return res.json();
    }}

    getJSON('/health').then(d => {{
      document.getElementById('healthVal').textContent = (d && d.status) || 'ok';
    }}).catch(_ => {{
      document.getElementById('healthVal').textContent = 'error';
    }});

    getJSON('/usage/summary').then(d => {{
      const v = d.requests_24h ?? d.requests ?? JSON.stringify(d);
      document.getElementById('usageVal').textContent = v;
    }}).catch(_ => {{
      document.getElementById('usageVal').textContent = 'unauth';
    }});

    getJSON('/ads/customers').then(d => {{
      const n = Array.isArray(d) ? d.length : (d.customers?.length || 0);
      document.getElementById('custVal').textContent = n;
    }}).catch(_ => {{
      document.getElementById('custVal').textContent = 'unauth';
    }});
    
    function normCID(s) {{ return (s || '').replace(/[^0-9]/g, ''); }}
    document.getElementById('openAnalytics').addEventListener('click', () => {{
      const cid = normCID(document.getElementById('cidInput').value);
      if (!cid) {{ document.getElementById('anStatus').textContent = 'Enter a customer ID.'; return; }}
      document.getElementById('anStatus').textContent = 'Opening…';
      const url = '/misc/analytics?customer_id=' + encodeURIComponent(cid) + (token ? ('&key=' + encodeURIComponent(token)) : '');
      window.open(url, '_blank');
      setTimeout(() => {{ document.getElementById('anStatus').textContent = 'Opened analytics.'; }}, 600);
    }});
    document.getElementById('cidInput').addEventListener('keydown', (e) => {{ if (e.key === 'Enter') document.getElementById('openAnalytics').click(); }});
  </script>
</body>
</html>""")


@router.get("/analytics", response_class=HTMLResponse)
async def misc_analytics(request: Request, customer_id: str, key: str | None = None):
    """Multi-level analytics dashboard (campaign, ad group, ad, keyword)."""
    token = key or request.query_params.get(
        "key") or request.headers.get("authorization")
    if token and token.lower().startswith("bearer "):
        token = token.split(" ", 1)[1]
    safe_token = html.escape(token or "")
    cid_norm = ''.join(ch for ch in customer_id if ch.isdigit())
    return HTMLResponse(f"""<!doctype html>
<html lang='en'>
<head>
  <meta charset='utf-8'/>
  <title>Analytics — {cid_norm}</title>
  <meta name='viewport' content='width=device-width,initial-scale=1'/>
  <style>
    body{{margin:0;font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial;background:#0b1220;color:#e6edf3}}a{{color:#93c5fd;text-decoration:none}}a:hover{{text-decoration:underline}}
    header{{padding:14px 18px;background:#0f172a;border-bottom:1px solid #1f2937;display:flex;flex-wrap:wrap;align-items:center;gap:14px}}
    .chip{{background:#111827;border:1px solid #1f2937;border-radius:12px;padding:6px 12px;font-size:13px}}
    main{{max-width:1200px;margin:20px auto;padding:0 18px}}
    .tabs{{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px}}
    .tab{{cursor:pointer;padding:8px 14px;border:1px solid #1f2937;border-radius:10px;background:#111827;font-size:13px}}
    .tab.active{{background:#1e293b}}
    table{{width:100%;border-collapse:collapse;font-size:13px}}
    th,td{{padding:6px 8px;border-bottom:1px solid #1f2937;text-align:right}}
    th:first-child,td:first-child{{text-align:left}}
    #status{{font-size:12px;color:#94a3b8;margin:8px 0 4px}}
    .controls{{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 6px}}
    input[type=text]{{background:#0b1220;color:#e6edf3;border:1px solid #1f2937;border-radius:8px;padding:6px 8px;width:200px}}
    label{{font-size:12px;color:#94a3b8;display:inline-flex;align-items:center;gap:4px}}
  </style>
</head>
<body>
  <header>
    <div class='chip'>📊 Analytics</div>
    <div class='chip'>Customer: <b>{cid_norm}</b></div>
    <div class='chip'>Token: <b>{'set' if safe_token else 'none'}</b></div>
    <a class='chip' href='/misc/dashboard'>← Back</a>
  </header>
  <main>
    <div class='controls'>
      <input id='cidInput' value='{cid_norm}' placeholder='Customer ID'/>
      <label><input id='incZero' type='checkbox'/> include zero impressions</label>
      <button id='reloadBtn' class='tab'>Reload</button>
    </div>
    <div class='tabs'>
      <div class='tab active' data-level='campaign'>Campaigns</div>
      <div class='tab' data-level='ad_group'>Ad Groups</div>
      <div class='tab' data-level='ad'>Ads</div>
      <div class='tab' data-level='keyword'>Keywords</div>
    </div>
    <div id='status'>Ready.</div>
    <div style='overflow:auto'>
      <table id='dataTbl'>
        <thead><tr id='hdrRow'></tr></thead>
        <tbody id='bodyRows'></tbody>
      </table>
    </div>
  </main>
  <script>
    const injectedToken = "{safe_token}";
    let currentLevel = 'campaign';
    function normCID(s) {{ return (s || '').replace(/[^0-9]/g,''); }}
    const tabs = document.querySelectorAll('.tab');
    tabs.forEach(t => t.addEventListener('click', () => {{ tabs.forEach(x => x.classList.remove('active')); t.classList.add('active'); currentLevel = t.dataset.level; loadData(); }}));
    document.getElementById('reloadBtn').addEventListener('click', loadData);
    document.getElementById('cidInput').addEventListener('keydown', e => {{ if (e.key === 'Enter') loadData(); }});
    function headersFor(level) {{
      if (level === 'campaign') return ['Campaign','Impr','Clicks','Cost','Conv','Conv Value','Status'];
      if (level === 'ad_group') return ['Ad Group','Campaign','Impr','Clicks','Cost','Conv','Conv Value','Status'];
      if (level === 'ad') return ['Ad ID','Type','Ad Group','Campaign','Impr','Clicks','Cost','Conv','Conv Value','Status'];
      if (level === 'keyword') return ['Keyword','Match','Ad Group','Campaign','Impr','Clicks','Cost','Conv','Conv Value','Status'];
      return ['Item','Impr','Clicks','Cost'];
    }}
    function rowMap(level, r) {{
      if (level === 'campaign') return [r.name || r.campaign_id, r.impressions || 0, r.clicks || 0, fmtCost(r.cost), fmtNum(r.conversions), fmtNum(r.conv_value), r.status || ''];
      if (level === 'ad_group') return [r.ad_group_name || r.ad_group_id, r.campaign_name || r.campaign_id, r.impressions || 0, r.clicks || 0, fmtCost(r.cost), fmtNum(r.conversions), fmtNum(r.conv_value), r.status || ''];
      if (level === 'ad') return [r.ad_id, r.ad_type || '', r.ad_group_name || r.ad_group_id, r.campaign_name || r.campaign_id, r.impressions || 0, r.clicks || 0, fmtCost(r.cost), fmtNum(r.conversions), fmtNum(r.conv_value), r.status || ''];
      if (level === 'keyword') return [r.text || '', r.match_type || '', r.ad_group_name || r.ad_group_id, r.campaign_name || r.campaign_id, r.impressions || 0, r.clicks || 0, fmtCost(r.cost), fmtNum(r.conversions), fmtNum(r.conv_value), r.status || ''];
      return [r.name || '', r.impressions || 0, r.clicks || 0, fmtCost(r.cost)];
    }}
    function fmtCost(v) {{ return (v || 0).toLocaleString(undefined, {{minimumFractionDigits:2, maximumFractionDigits:2}}); }}
    function fmtNum(v) {{ return (v || 0).toLocaleString(); }}
    async function loadData() {{
      const cid = normCID(document.getElementById('cidInput').value);
      if (!cid) {{ document.getElementById('status').textContent = 'Enter CID.'; return; }}
      document.getElementById('status').textContent = 'Loading ' + currentLevel + '…';
      const inc0 = document.getElementById('incZero').checked ? '&include_zero_impressions=true' : '';
      const headers = injectedToken ? {{ 'Authorization': 'Bearer ' + injectedToken }} : {{}};
      try {{
        const resp = await fetch(`/ads/report-mtd?customer_id=${{cid}}&level=${{currentLevel}}${{inc0}}`, {{ headers }});
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const data = await resp.json();
        const rows = data.rows || [];
        const hdrs = headersFor(currentLevel);
        const hdrRow = document.getElementById('hdrRow');
        hdrRow.innerHTML = '';
        hdrs.forEach(h => {{ const th = document.createElement('th'); th.textContent = h; hdrRow.appendChild(th); }});
        const body = document.getElementById('bodyRows'); body.innerHTML = '';
        rows.forEach(r => {{ const tr = document.createElement('tr'); const cols = rowMap(currentLevel, r); cols.forEach((c, i) => {{ const td = document.createElement('td'); td.textContent = c; tr.appendChild(td); }}); body.appendChild(tr); }});
        document.getElementById('status').textContent = `${{rows.length}} row(s)`;
      }} catch (err) {{ document.getElementById('status').textContent = 'Error loading data'; }}
    }}
    loadData();
  </script>
</body>
</html>""")


# ---------------------------
# MTD Report Dashboard (focused)
# ---------------------------

@router.get("/analytics-mtd", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def analytics_mtd(request: Request):
    """Focused dashboard for /ads/report-mtd across selectable levels.

    Features:
      - Customer ID input (normalizes digits only, persists in localStorage)
      - Level selector (campaign/ad_group/ad/keyword)
      - Include zero impressions toggle
      - Live summary chips (total rows, impressions, clicks, cost, conversions, conv value)
      - Download CSV button
    """
    return HTMLResponse("""<!doctype html>
<html lang='en'>
<head>
  <meta charset='utf-8'/>
  <title>MTD Report Dashboard</title>
  <meta name='viewport' content='width=device-width,initial-scale=1'/>
  <style>
    body{margin:0;font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial;background:#0b1220;color:#e6edf3}
    a{color:#93c5fd;text-decoration:none}a:hover{text-decoration:underline}
    header{padding:14px 18px;background:#0f172a;border-bottom:1px solid #1f2937;display:flex;flex-wrap:wrap;align-items:center;gap:14px}
    .chip{background:#111827;border:1px solid #1f2937;border-radius:12px;padding:6px 12px;font-size:13px}
    main{max-width:1200px;margin:20px auto;padding:0 18px}
    .controls{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:14px}
    input[type=text]{background:#0b1220;color:#e6edf3;border:1px solid #1f2937;border-radius:8px;padding:6px 8px;width:200px}
    label{font-size:12px;color:#94a3b8;display:inline-flex;align-items:center;gap:4px}
    select{background:#0b1220;color:#e6edf3;border:1px solid #1f2937;border-radius:8px;padding:6px 8px}
    button{background:#111827;color:#e6edf3;border:1px solid #1f2937;border-radius:8px;padding:6px 14px;cursor:pointer;font-size:13px}
    button:hover{background:#1e293b}
    table{width:100%;border-collapse:collapse;font-size:13px;margin-top:10px}
    th,td{padding:6px 8px;border-bottom:1px solid #1f2937;text-align:right}
    th:first-child,td:first-child{text-align:left}
    #summary{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0}
    .sum{background:#111827;border:1px solid #1f2937;border-radius:10px;padding:6px 10px;font-size:12px}
  </style>
</head>
<body>
  <header>
    <div class='chip'>📊 MTD Report</div>
    <a class='chip' href='/misc/dashboard'>← Dashboard</a>
  </header>
  <main>
    <div class='controls'>
      <input id='cidInput' placeholder='Customer ID (e.g. 7414394764)' />
      <select id='levelSel'>
        <option value='campaign'>Campaign</option>
        <option value='ad_group'>Ad Group</option>
        <option value='ad'>Ad</option>
        <option value='keyword'>Keyword</option>
      </select>
      <label><input id='incZero' type='checkbox'/> include zero impressions</label>
      <button id='loadBtn'>Load</button>
      <button id='csvBtn' disabled>Download CSV</button>
    </div>
    <div id='status' style='font-size:12px;color:#94a3b8'>Ready.</div>
    <div id='summary'></div>
    <div style='overflow:auto'>
      <table id='dataTbl'>
        <thead><tr id='hdrRow'></tr></thead>
        <tbody id='bodyRows'></tbody>
      </table>
    </div>
  </main>
  <script type='module'>
    import { attachCID } from '/misc/cid.js';
    const cidCtl = attachCID(document.getElementById('cidInput'), { onEnter: () => loadData() });
    const _qs = new URLSearchParams(location.search); const _qcid = _qs.get('customer_id'); if(_qcid){ cidCtl.set(_qcid); }
    const _qs = new URLSearchParams(location.search); const _qcid = _qs.get('customer_id'); if(_qcid){ cidCtl.set(_qcid); }
    const levelSel = document.getElementById('levelSel');
    const incZero = document.getElementById('incZero');
    const statusEl = document.getElementById('status');
    const hdrRow = document.getElementById('hdrRow');
    const bodyRows = document.getElementById('bodyRows');
    const sumBox = document.getElementById('summary');
    const csvBtn = document.getElementById('csvBtn');
    document.getElementById('loadBtn').addEventListener('click', loadData);
    function getCID(){ return cidCtl.get(); }
    function headersFor(level){
      if(level==='campaign') return ['Campaign','Impr','Clicks','Cost','Conv','Conv Value','Status'];
      if(level==='ad_group') return ['Ad Group','Campaign','Impr','Clicks','Cost','Conv','Conv Value','Status'];
      if(level==='ad') return ['Ad ID','Type','Ad Group','Campaign','Impr','Clicks','Cost','Conv','Conv Value','Status'];
      if(level==='keyword') return ['Keyword','Match','Ad Group','Campaign','Impr','Clicks','Cost','Conv','Conv Value','Status'];
      return ['Item','Impr','Clicks','Cost'];
    }
    function rowMap(level,r){
      if(level==='campaign') return [r.name||r.campaign_id,r.impressions||0,r.clicks||0,fmtCost(r.cost),fmtNum(r.conversions),fmtNum(r.conv_value),r.status||''];
      if(level==='ad_group') return [r.ad_group_name||r.ad_group_id,r.campaign_name||r.campaign_id,r.impressions||0,r.clicks||0,fmtCost(r.cost),fmtNum(r.conversions),fmtNum(r.conv_value),r.status||''];
      if(level==='ad') return [r.ad_id,r.ad_type||'',r.ad_group_name||r.ad_group_id,r.campaign_name||r.campaign_id,r.impressions||0,r.clicks||0,fmtCost(r.cost),fmtNum(r.conversions),fmtNum(r.conv_value),r.status||''];
      if(level==='keyword') return [r.text||'',r.match_type||'',r.ad_group_name||r.ad_group_id,r.campaign_name||r.campaign_id,r.impressions||0,r.clicks||0,fmtCost(r.cost),fmtNum(r.conversions),fmtNum(r.conv_value),r.status||''];
      return [r.name||'',r.impressions||0,r.clicks||0,fmtCost(r.cost)];
    }
    function fmtCost(v){return (v||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});}
    function fmtNum(v){return (v||0).toLocaleString();}
    function aggregate(level, rows){
      let impr=0,clicks=0,cost=0,conv=0,convValue=0;
      rows.forEach(r=>{impr+=r.impressions||0;clicks+=r.clicks||0;cost+=r.cost||0;conv+=r.conversions||0;convValue+=r.conv_value||0;});
      return {impr,clicks,cost,conv,convValue};
    }
    function toCSV(level, rows){
      const hdr = headersFor(level);
      const lines = [hdr.join(',')];
      rows.forEach(r=>{lines.push(rowMap(level,r).map(x=>(''+x).replace(/"/g,'""')).join(','));});
      return lines.join('\n');
    }
    async function loadData(){
      const cid = getCID();
      if(!cid){statusEl.textContent='Enter CID.';return;}
      const level = levelSel.value;
      const inc0 = incZero.checked ? '&include_zero_impressions=true' : '';
      statusEl.textContent='Loading '+level+'…';
      try{
        const resp = await fetch(`/ads/report-mtd?customer_id=${cid}&level=${level}${inc0}`);
        if(!resp.ok) throw new Error('HTTP '+resp.status);
        const data = await resp.json();
        const rows = data.rows || [];
        hdrRow.innerHTML=''; headersFor(level).forEach(h=>{const th=document.createElement('th'); th.textContent=h; hdrRow.appendChild(th);});
        bodyRows.innerHTML=''; rows.forEach(r=>{const tr=document.createElement('tr'); rowMap(level,r).forEach(c=>{const td=document.createElement('td'); td.textContent=c; tr.appendChild(td);}); bodyRows.appendChild(tr);});
        const agg = aggregate(level, rows);
        sumBox.innerHTML='';
        const sums=[['Rows',rows.length],['Impr',agg.impr],['Clicks',agg.clicks],['Cost',fmtCost(agg.cost)],['Conv',fmtNum(agg.conv)],['Conv Value',fmtNum(agg.convValue)]];
        sums.forEach(([k,v])=>{const d=document.createElement('div'); d.className='sum'; d.textContent=k+': '+v; sumBox.appendChild(d);});
        csvBtn.disabled = rows.length===0;
        csvBtn.onclick = ()=>{const blob=new Blob([toCSV(level,rows)],{type:'text/csv'}); const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download=`mtd_${cid}_${level}.csv`; a.click();};
        statusEl.textContent=rows.length+' row(s)';
      }catch(e){statusEl.textContent='Error loading data';}
    }
  </script>
</body>
</html>""")


# ---------------------------
# YTD Daily Dashboard (campaign level persistence-aware)
# ---------------------------

@router.get("/analytics-ytd-daily", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def analytics_ytd_daily(request: Request):
    """Dashboard for /ads/report-ytd-daily with source + fill_missing controls.

    Shows:
      - Source indicator (db/live/auto) with color
      - Optional fill_missing toggle (only when source auto/db)
      - Daily campaign rows (aggregated per day+campaign from fact table or live)
      - Summary chips (days covered, campaigns, impressions, clicks, cost, conversions, conv value)
      - CSV download (delegates to API format=csv for consistency)
      - Newly ingested days highlighted when fill_missing triggered
    """
    return HTMLResponse("""<!doctype html>
<html lang='en'>
<head>
  <meta charset='utf-8'/>
  <title>YTD Daily Dashboard</title>
  <meta name='viewport' content='width=device-width,initial-scale=1'/>
  <style>
    body{margin:0;font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial;background:#0b1220;color:#e6edf3}
    header{padding:14px 18px;background:#0f172a;border-bottom:1px solid #1f2937;display:flex;flex-wrap:wrap;gap:14px;align-items:center}
    a{color:#93c5fd;text-decoration:none}a:hover{text-decoration:underline}
    .chip{background:#111827;border:1px solid #1f2937;border-radius:12px;padding:6px 12px;font-size:13px}
    main{max-width:1300px;margin:18px auto;padding:0 18px}
    .controls{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:14px}
    input[type=text],select{background:#0b1220;color:#e6edf3;border:1px solid #1f2937;border-radius:8px;padding:6px 8px}
    button{background:#111827;color:#e6edf3;border:1px solid #1f2937;border-radius:8px;padding:6px 14px;cursor:pointer;font-size:13px}
    button:hover{background:#1e293b}
    table{width:100%;border-collapse:collapse;font-size:12px;margin-top:12px}
    th,td{padding:5px 6px;border-bottom:1px solid #1f2937;text-align:right}
    th:first-child,td:first-child{text-align:left}
    #summary{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0}
    .sum{background:#111827;border:1px solid #1f2937;border-radius:10px;padding:6px 10px;font-size:12px}
    .src-db{color:#22c55e}
    .src-live{color:#fbbf24}
    .src-auto{color:#60a5fa}
    .ingested{background:#064e3b !important;color:#d1fae5}
  </style>
</head>
<body>
  <header>
    <div class='chip'>📅 YTD Daily</div>
    <a class='chip' href='/misc/dashboard'>← Dashboard</a>
  </header>
  <main>
    <div class='controls'>
      <input id='cidInput' placeholder='Customer ID' />
      <select id='sourceSel'>
        <option value='auto'>auto (DB prefer)</option>
        <option value='db'>db only</option>
        <option value='live'>live only</option>
      </select>
  <label style='font-size:12px;color:#94a3b8'><input id='fillMissing' type='checkbox'/> fill missing days (auto/db only)</label>
      <label style='font-size:12px;color:#94a3b8'><input id='incZero' type='checkbox'/> include zero impressions</label>
      <button id='loadBtn'>Load</button>
      <button id='csvBtn' disabled>CSV</button>
      <div id='srcIndicator' style='font-size:12px;margin-left:6px'></div>
    </div>
    <div id='status' style='font-size:12px;color:#94a3b8'>Ready.</div>
    <div id='summary'></div>
    <div style='max-height:65vh;overflow:auto'>
      <table id='tbl'>
        <thead><tr id='hdr'></tr></thead>
        <tbody id='rows'></tbody>
      </table>
    </div>
  </main>
  <script type='module'>
    import { attachCID } from '/misc/cid.js';
    const cidCtl = attachCID(document.getElementById('cidInput'), { onEnter: () => loadData() });
    const sourceSel = document.getElementById('sourceSel');
    const fillMissing = document.getElementById('fillMissing');
    const incZero = document.getElementById('incZero');
    const statusEl = document.getElementById('status');
    const hdr = document.getElementById('hdr');
    const rowsEl = document.getElementById('rows');
    const sumEl = document.getElementById('summary');
    const csvBtn = document.getElementById('csvBtn');
    const srcIndicator = document.getElementById('srcIndicator');
    document.getElementById('loadBtn').addEventListener('click', loadData);
    function hdrs(){return ['Day','Campaign','Status','Impr','Clicks','Cost','Conv','Conv Value'];}
    function fmtCost(v){return (v||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});}
    function fmtNum(v){return (v||0).toLocaleString();}
    function updateSourceTag(s){
      const cls = s==='db'?'src-db':(s==='live'?'src-live':'src-auto');
      srcIndicator.className=cls; srcIndicator.textContent='source: '+s;
    }
    async function loadData(){
      const cid = cidCtl.get(); if(!cid){statusEl.textContent='Enter CID.'; return;}
      const src = sourceSel.value; const fm = fillMissing.checked; const inc0 = incZero.checked;
      if(src==='live'){ fillMissing.checked=false; }
      const q = `/ads/report-ytd-daily?customer_id=${cid}&source=${src}${fm?'&fill_missing=true':''}${inc0?'&include_zero_impressions=true':''}`;
      statusEl.textContent='Loading…';
      try {
        const resp = await fetch(q);
        if(!resp.ok) throw new Error('HTTP '+resp.status);
        const data = await resp.json();
        updateSourceTag(data.source||src);
        const rows = data.rows||[];
        hdr.innerHTML=''; hdrs().forEach(h=>{const th=document.createElement('th'); th.textContent=h; hdr.appendChild(th);});
        rowsEl.innerHTML='';
        const ingestedSet = new Set((data.ingested_days||[]));
        rows.forEach(r=>{
          const tr=document.createElement('tr');
          if(ingestedSet.has(r.day)) tr.className='ingested';
          const cols=[r.day,r.name||r.campaign_id,r.status||'',r.impressions||0,r.clicks||0,fmtCost(r.cost),fmtNum(r.conversions),fmtNum(r.conv_value)];
          cols.forEach(c=>{const td=document.createElement('td'); td.textContent=c; tr.appendChild(td);});
          rowsEl.appendChild(tr);
        });
        // aggregates
        let days = new Set(rows.map(r=>r.day));
        let campaigns = new Set(rows.map(r=>r.campaign_id));
        let agg={impr:0,clicks:0,cost:0,conv:0,convValue:0};
        rows.forEach(r=>{agg.impr+=r.impressions||0; agg.clicks+=r.clicks||0; agg.cost+=r.cost||0; agg.conv+=r.conversions||0; agg.convValue+=r.conv_value||0;});
        sumEl.innerHTML='';
        const chips=[['Rows',rows.length],['Days',days.size],['Campaigns',campaigns.size],['Impr',agg.impr],['Clicks',agg.clicks],['Cost',fmtCost(agg.cost)],['Conv',fmtNum(agg.conv)],['Conv Value',fmtNum(agg.convValue)]];
        chips.forEach(([k,v])=>{const d=document.createElement('div'); d.className='sum'; d.textContent=k+': '+v; sumEl.appendChild(d);});
        csvBtn.disabled = rows.length===0; csvBtn.onclick = ()=>{window.open(q+'&format=csv','_blank');};
        statusEl.textContent=rows.length+' row(s)';
      } catch(err){ statusEl.textContent='Error loading'; }
    }
  </script>
</body>
</html>""")


# ---------------------------
# Keyword Ideas Dashboard
# ---------------------------

@router.get("/analytics-keyword-ideas", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def analytics_keyword_ideas(request: Request):
    """Interactive UI for /ads/keyword-ideas.

    Inputs:
      - Customer ID (shared CID module)
      - Seed keywords (comma separated)
      - URL (optional)
      - Geo IDs (comma separated; default 2840)
      - Language ID (default 1000)
      - Network (google | partners)
      - Limit (1..800)

    Features:
      - Sorting on columns (idea, avg searches, competition, low/high bid)
      - Live count & aggregate suggested bid range statistics
      - CSV export (client side) and JSON raw preview toggle
      - Basic validation: require either seed or URL
    """
    return HTMLResponse("""<!doctype html>
<html lang='en'>
<head>
  <meta charset='utf-8'/>
  <title>Keyword Ideas Dashboard</title>
  <meta name='viewport' content='width=device-width,initial-scale=1'/>
  <style>
    body{margin:0;font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial;background:#0b1220;color:#e6edf3}
    header{padding:14px 18px;background:#0f172a;border-bottom:1px solid #1f2937;display:flex;flex-wrap:wrap;gap:14px;align-items:center}
    a{color:#93c5fd;text-decoration:none}a:hover{text-decoration:underline}
    .chip{background:#111827;border:1px solid #1f2937;border-radius:12px;padding:6px 12px;font-size:13px}
    main{max-width:1200px;margin:18px auto;padding:0 18px}
    .controls{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:14px}
    input[type=text],select{background:#0b1220;color:#e6edf3;border:1px solid #1f2937;border-radius:8px;padding:6px 8px;font-size:13px}
    button{background:#111827;color:#e6edf3;border:1px solid #1f2937;border-radius:8px;padding:6px 14px;cursor:pointer;font-size:13px}
    button:hover{background:#1e293b}
    table{width:100%;border-collapse:collapse;font-size:12px;margin-top:12px}
    th,td{padding:5px 6px;border-bottom:1px solid #1f2937;text-align:right;cursor:default}
    th:first-child,td:first-child{text-align:left}
    th.sortable{cursor:pointer}
    #summary{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0}
    .sum{background:#111827;border:1px solid #1f2937;border-radius:10px;padding:6px 10px;font-size:12px}
    .warn{color:#fbbf24;font-size:12px}
    .error{color:#f87171;font-size:12px}
    pre{background:#111827;padding:10px;border-radius:8px;overflow:auto;font-size:11px}
  </style>
</head>
<body>
  <header>
    <div class='chip'>🔑 Keyword Ideas</div>
    <a class='chip' href='/misc/dashboard'>← Dashboard</a>
  </header>
  <main>
    <div class='controls'>
      <input id='cidInput' placeholder='Customer ID' />
      <input id='seedInput' placeholder='Seed keywords (comma separated)' style='flex:1;min-width:200px' />
      <input id='urlInput' placeholder='URL (optional)' style='flex:1;min-width:160px' />
      <input id='geoInput' placeholder='Geo IDs (comma, default 2840)' value='2840' />
      <input id='langInput' placeholder='Lang ID (default 1000)' value='1000' />
      <select id='networkSel'>
        <option value='google'>Google Search</option>
        <option value='partners'>Google Search & Partners</option>
      </select>
      <input id='limitInput' placeholder='Limit (<=800)' value='100' />
      <button id='loadBtn'>Fetch</button>
      <button id='csvBtn' disabled>CSV</button>
      <button id='toggleRaw'>Raw JSON</button>
    </div>
    <div id='status' style='font-size:12px;color:#94a3b8'>Ready.</div>
    <div id='summary'></div>
    <div style='max-height:55vh;overflow:auto'>
      <table id='tbl'>
        <thead><tr id='hdr'></tr></thead>
        <tbody id='rows'></tbody>
      </table>
    </div>
    <div id='rawBox' style='display:none;margin-top:14px'></div>
  </main>
  <script type='module'>
    import { attachCID } from '/misc/cid.js';
    const cidCtl = attachCID(document.getElementById('cidInput'), { onEnter: () => loadData() });
    const seedInput = document.getElementById('seedInput');
    const urlInput = document.getElementById('urlInput');
    const geoInput = document.getElementById('geoInput');
    const langInput = document.getElementById('langInput');
    const networkSel = document.getElementById('networkSel');
    const limitInput = document.getElementById('limitInput');
    const statusEl = document.getElementById('status');
    const summaryEl = document.getElementById('summary');
    const hdrEl = document.getElementById('hdr');
    const rowsEl = document.getElementById('rows');
    const csvBtn = document.getElementById('csvBtn');
    const rawBtn = document.getElementById('toggleRaw');
    const rawBox = document.getElementById('rawBox');
    document.getElementById('loadBtn').addEventListener('click', loadData);
    rawBtn.addEventListener('click', ()=>{ rawBox.style.display = rawBox.style.display==='none' ? 'block' : 'none'; rawBtn.textContent = rawBox.style.display==='none' ? 'Raw JSON' : 'Hide Raw'; });
    const sortableCols = ['idea','avg_monthly_searches','competition','low_top_of_page_bid','high_top_of_page_bid'];
    let currentSort = { key: 'avg_monthly_searches', dir: 'desc' };
    function hdrs(){return [
      ['idea','Keyword'],
      ['avg_monthly_searches','Avg Monthly Searches'],
      ['competition','Competition'],
      ['low_top_of_page_bid','Low Bid'],
      ['high_top_of_page_bid','High Bid']
    ];}
    function applySort(data){
      const { key, dir } = currentSort; const mul = dir==='asc'?1:-1;
      data.sort((a,b)=>{
        const va=a[key]; const vb=b[key];
        if(va==null && vb==null) return 0; if(va==null) return 1; if(vb==null) return -1;
        if(typeof va === 'number' && typeof vb === 'number') return (va-vb)*mul;
        return (''+va).localeCompare(''+vb)*mul;
      });
    }
    function render(data){
      hdrEl.innerHTML=''; hdrs().forEach(([k,label])=>{const th=document.createElement('th'); th.textContent=label; if(sortableCols.includes(k)){ th.className='sortable'; th.onclick=()=>{ if(currentSort.key===k){ currentSort.dir = currentSort.dir==='asc'?'desc':'asc'; } else { currentSort.key=k; currentSort.dir='desc'; } render(data); }; } hdrEl.appendChild(th); });
      rowsEl.innerHTML=''; applySort(data); data.forEach(r=>{const tr=document.createElement('tr'); const cols=[r.idea,r.avg_monthly_searches??'—',r.competition??'—',r.low_top_of_page_bid??'—',r.high_top_of_page_bid??'—']; cols.forEach(c=>{const td=document.createElement('td'); td.textContent=c; tr.appendChild(td);}); rowsEl.appendChild(tr);});
    }
    function toCSV(data){
      const header=['idea','avg_monthly_searches','competition','low_top_of_page_bid','high_top_of_page_bid'];
      const lines=[header.join(',')];
      data.forEach(r=>{lines.push(header.map(h=>(''+(r[h]??'')).replace(/"/g,'""')).join(','));});
      return lines.join('\n');
    }
    async function loadData(){
      const cid = cidCtl.get(); if(!cid){statusEl.textContent='Enter CID.'; return;}
      const seed = seedInput.value.trim();
      const url = urlInput.value.trim();
      const geo = geoInput.value.trim() || '2840';
      const lang = (langInput.value.trim() || '1000').replace(/[^0-9]/g,'');
      const network = networkSel.value;
      const limit = Math.min(Math.max(parseInt(limitInput.value||'100',10),1),800);
      if(!seed && !url){ statusEl.textContent='Provide seed or URL'; return; }
      statusEl.textContent='Loading…';
      try {
        const params = new URLSearchParams({ customer_id: cid, geo, lang, network, limit: String(limit) });
        if(seed) params.set('seed', seed);
        if(url) params.set('url', url);
        const resp = await fetch('/ads/keyword-ideas?' + params.toString());
        if(!resp.ok) throw new Error('HTTP '+resp.status);
        const data = await resp.json();
        const ideas = data.ideas||[];
        render(ideas);
        // aggregates
        let avgSearchTotal=0, bids=[];
        ideas.forEach(r=>{ if(typeof r.avg_monthly_searches==='number') avgSearchTotal+=r.avg_monthly_searches; ['low_top_of_page_bid','high_top_of_page_bid'].forEach(k=>{ const v=r[k]; if(typeof v==='number') bids.push(v); }); });
        const avgSearch = ideas.length? Math.round(avgSearchTotal/ideas.length):0;
        const bidMin = bids.length? Math.min(...bids):0;
        const bidMax = bids.length? Math.max(...bids):0;
        summaryEl.innerHTML='';
        const chips=[['Ideas',ideas.length],['Avg Searches/Idea',avgSearch],['Min Bid',bidMin.toFixed(2)],['Max Bid',bidMax.toFixed(2)],['Network',data.network]];
        chips.forEach(([k,v])=>{const d=document.createElement('div'); d.className='sum'; d.textContent=k+': '+v; summaryEl.appendChild(d);});
        csvBtn.disabled = ideas.length===0; csvBtn.onclick = ()=>{ const blob=new Blob([toCSV(ideas)],{type:'text/csv'}); const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download=`ideas_${cid}.csv`; a.click(); };
        rawBox.innerHTML = '<pre>'+htmlEscape(JSON.stringify(data,null,2))+'</pre>';
        statusEl.textContent = ideas.length+' idea(s)';
      } catch(err){ statusEl.textContent='Error loading'; }
    }
    function htmlEscape(s){ return s.replace(/[&<>]/g,c=>({ '&':'&amp;','<':'&lt;','>':'&gt;' })[c]); }
  </script>
</body>
</html>""")


# ---------------------------
# ETL Runner & Missing Days Dashboard
# ---------------------------

@router.get("/analytics-etl", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def analytics_etl(request: Request):
    """Dashboard to inspect missing perf days and trigger ETL ingestion.

    Uses /etl/missing-days and /etl/run-day endpoints.
    Allows:
      - Select level (campaign|ad_group|ad|keyword) — campaign primary
      - Choose date range (start/end) default Jan1..today
      - Fetch missing days list
      - Ingest individual day or all missing days (sequential with progress)
      - Multi-level ingestion by specifying additional levels (comma separated)
      - Status log area
    """
    from datetime import date
    today = date.today()
    jan1 = date(today.year, 1, 1)
    return HTMLResponse(f"""<!doctype html>
<html lang='en'>
<head>
  <meta charset='utf-8'/>
  <title>ETL Runner & Missing Days</title>
  <meta name='viewport' content='width=device-width,initial-scale=1'/>
  <style>
    body{{margin:0;font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial;background:#0b1220;color:#e6edf3}}
    header{{padding:14px 18px;background:#0f172a;border-bottom:1px solid #1f2937;display:flex;flex-wrap:wrap;align-items:center;gap:14px}}
    a{{color:#93c5fd;text-decoration:none}}a:hover{{text-decoration:underline}}
    .chip{{background:#111827;border:1px solid #1f2937;border-radius:12px;padding:6px 12px;font-size:13px}}
    main{{max-width:1200px;margin:18px auto;padding:0 18px}}
    .controls{{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:14px}}
    input[type=text],input[type=date],select{{background:#0b1220;color:#e6edf3;border:1px solid #1f2937;border-radius:8px;padding:6px 8px}}
    button{{background:#111827;color:#e6edf3;border:1px solid #1f2937;border-radius:8px;padding:6px 14px;cursor:pointer;font-size:13px}}
    button:hover{{background:#1e293b}}
    table{{width:100%;border-collapse:collapse;font-size:12px;margin-top:12px}}
    th,td{{padding:5px 6px;border-bottom:1px solid #1f2937;text-align:left}}
    #log{{background:#111827;padding:10px;border-radius:8px;font-size:11px;white-space:pre-wrap;max-height:200px;overflow:auto}}
    .pill{{display:inline-block;background:#111827;border:1px solid #1f2937;border-radius:10px;padding:4px 8px;font-size:11px;margin:4px 4px 0 0}}
    .ok{{color:#22c55e}} .err{{color:#f87171}} .warn{{color:#fbbf24}}
  </style>
</head>
<body>
  <header>
    <div class='chip'>🛠️ ETL Runner</div>
    <a class='chip' href='/misc/dashboard'>← Dashboard</a>
  </header>
  <main>
    <div class='controls'>
      <input id='cidInput' placeholder='Customer ID' />
      <select id='levelSel'>
        <option value='campaign'>campaign</option>
        <option value='ad_group'>ad_group</option>
        <option value='ad'>ad</option>
        <option value='keyword'>keyword</option>
      </select>
      <input id='extraLevels' placeholder='additional levels (comma optional)' style='min-width:180px' />
      <input id='startDate' type='date' value='{jan1.isoformat()}' />
      <input id='endDate' type='date' value='{today.isoformat()}' />
      <button id='btnFetch'>Missing Days</button>
      <button id='btnIngestAll' disabled>Ingest All Missing</button>
    </div>
    <div id='status' style='font-size:12px;color:#94a3b8'>Ready.</div>
    <div id='summary'></div>
    <table id='daysTbl'><thead><tr><th>Day</th><th>Action</th><th>Status</th></tr></thead><tbody id='daysBody'></tbody></table>
    <h4 style='margin-top:18px'>Log</h4>
    <div id='log'>—</div>
  </main>
  <script type='module'>
    import {{ attachCID }} from '/misc/cid.js';
    const cidCtl = attachCID(document.getElementById('cidInput'), {{ onEnter: () => fetchMissing() }});
    const levelSel = document.getElementById('levelSel');
    const extraLevels = document.getElementById('extraLevels');
    const startDate = document.getElementById('startDate');
    const endDate = document.getElementById('endDate');
    const statusEl = document.getElementById('status');
    const daysBody = document.getElementById('daysBody');
    const summaryEl = document.getElementById('summary');
    const logEl = document.getElementById('log');
    const btnFetch = document.getElementById('btnFetch');
    const btnIngestAll = document.getElementById('btnIngestAll');
    btnFetch.addEventListener('click', fetchMissing);
    btnIngestAll.addEventListener('click', () => ingestAll());
    function log(msg, cls=''){{ const line = document.createElement('div'); if(cls) line.className=cls; line.textContent = '['+new Date().toISOString()+'] '+msg; logEl.appendChild(line); logEl.scrollTop = logEl.scrollHeight; }}
    function clearLog(){{ logEl.innerHTML=''; }}
    async function fetchMissing(){{
      const cid = cidCtl.get(); if(!cid){{statusEl.textContent='Enter CID';return;}}
      const lvl = levelSel.value;
      const start = startDate.value; const end = endDate.value;
      if(!start || !end){{ statusEl.textContent='Set start/end'; return; }}
      statusEl.textContent='Fetching missing…';
      try {{
        const url = `/etl/missing-days?customer_id=${{cid}}&start=${{start}}&end=${{end}}&level=${{lvl}}`;
        const resp = await fetch(url); if(!resp.ok) throw new Error('HTTP '+resp.status);
        const data = await resp.json();
        const missing = data.missing || [];
        summaryEl.innerHTML='';
        summaryEl.appendChild(chip('Level', lvl));
        summaryEl.appendChild(chip('Range', start+' → '+end));
        summaryEl.appendChild(chip('Missing', missing.length));
        summaryEl.appendChild(chip('Present', data.present_count||0));
        daysBody.innerHTML='';
        missing.forEach(d=>{{
          const tr=document.createElement('tr');
          const tdDay=document.createElement('td'); tdDay.textContent=d; tr.appendChild(tdDay);
          const tdAct=document.createElement('td');
          const btn=document.createElement('button'); btn.textContent='Ingest'; btn.onclick=()=>ingestDay(d,tr,btn);
          tdAct.appendChild(btn); tr.appendChild(tdAct);
          const tdStatus=document.createElement('td'); tdStatus.textContent='missing'; tr.appendChild(tdStatus);
          daysBody.appendChild(tr);
        }});
        btnIngestAll.disabled = missing.length===0;
        statusEl.textContent='Missing loaded';
  log('Fetched '+missing.length+' missing day(s)', 'ok');
      }} catch(err) {{ statusEl.textContent='Error'; log('Fetch error: '+err.message, 'err'); }}
    }}
    function chip(k,v){{ const d=document.createElement('div'); d.className='pill'; d.textContent=k+': '+v; return d; }}
    async function ingestDay(day, row, btn){{
      btn.disabled=true; const cid=cidCtl.get(); const levelsExtra=extraLevels.value.trim();
      const lvl=levelSel.value; const levelsParam = levelsExtra ? lvl+','+levelsExtra : '';
  let body = new URLSearchParams({'customer_id': cid, 'day': day });
      if(levelsParam) body.set('levels', levelsParam);
      statusEl.textContent='Ingesting '+day+'…';
      try {{
        const resp = await fetch('/etl/run-day?'+body.toString(), {{ method: 'POST' }});
        if(!resp.ok) throw new Error('HTTP '+resp.status);
        const data = await resp.json();
        row.children[2].textContent='ok'; row.children[2].className='ok';
        log('Ingested '+day+' (levels: '+(levelsParam||lvl)+')', 'ok');
      }} catch(err) {{ row.children[2].textContent='err'; row.children[2].className='err'; log('Ingest error '+day+': '+err.message, 'err'); }}
    }}
    async function ingestAll(){{
      const rows=[...daysBody.querySelectorAll('tr')];
      for(const r of rows){{ const day=r.children[0].textContent; const btn=r.children[1].querySelector('button'); if(btn && !btn.disabled) await ingestDay(day,r,btn); }}
      statusEl.textContent='Batch complete'; log('Batch ingest complete', 'ok');
    }}
  </script>
</body>
</html>""")


# ---------------------------
# Assist Answer Mini Console
# ---------------------------

@router.get("/assist-console", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def assist_console(request: Request):
    """Lightweight console to ask a question via /assist/answer.

    Controls:
      - Question textarea
      - k (top-k contexts), entity_type filter, scope_id (CID), model
      - Shows answer text and retrieved contexts summary
    """
    return HTMLResponse("""<!doctype html>
<html lang='en'>
<head>
  <meta charset='utf-8'/>
  <title>Assist Answer Console</title>
  <meta name='viewport' content='width=device-width,initial-scale=1'/>
  <style>
    body{margin:0;font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial;background:#0b1220;color:#e6edf3}
    header{padding:14px 18px;background:#0f172a;border-bottom:1px solid #1f2937;display:flex;gap:14px;align-items:center}
    a{color:#93c5fd;text-decoration:none}a:hover{text-decoration:underline}
    .chip{background:#111827;border:1px solid #1f2937;border-radius:12px;padding:6px 12px;font-size:13px}
    main{max-width:1000px;margin:18px auto;padding:0 18px}
    .row{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:12px}
    textarea,input,select{background:#0b1220;color:#e6edf3;border:1px solid #1f2937;border-radius:8px;padding:8px}
    textarea{width:100%;min-height:100px}
    button{background:#111827;color:#e6edf3;border:1px solid #1f2937;border-radius:8px;padding:8px 14px;cursor:pointer}
    button:hover{background:#1e293b}
    .sum{display:inline-block;background:#111827;border:1px solid #1f2937;border-radius:10px;padding:6px 10px;font-size:12px;margin-right:6px}
    pre{background:#111827;padding:10px;border-radius:8px;overflow:auto;font-size:12px}
  </style>
</head>
<body>
  <header>
    <div class='chip'>💬 Assist Answer</div>
    <a class='chip' href='/misc/dashboard'>← Dashboard</a>
  </header>
  <main>
    <div class='row'>
      <textarea id='q' placeholder='Ask a question about your Ads data...'></textarea>
    </div>
    <div class='row'>
      <input id='scopeId' placeholder='scope_id (CID, optional)' style='min-width:220px'>
      <input id='entityType' placeholder='entity_type (optional)' style='min-width:200px'>
      <input id='k' type='number' min='1' max='20' value='6' style='width:100px'>
      <input id='model' placeholder='model (optional)' style='min-width:200px'>
      <button id='ask'>Ask</button>
      <button id='clear'>Clear</button>
    </div>
    <div id='status' style='font-size:12px;color:#94a3b8'>Ready.</div>
    <div id='answerBox' style='margin-top:12px'></div>
    <div id='ctxBox' style='margin-top:12px'></div>
  </main>
  <script type='module'>
    import { attachCID } from '/misc/cid.js';
    const scopeCtl = attachCID(document.getElementById('scopeId'), { onEnter: () => ask() });
    const qEl = document.getElementById('q');
    const kEl = document.getElementById('k');
    const entEl = document.getElementById('entityType');
    const mdlEl = document.getElementById('model');
    const statusEl = document.getElementById('status');
    const ansEl = document.getElementById('answerBox');
    const ctxEl = document.getElementById('ctxBox');
    document.getElementById('ask').addEventListener('click', ask);
    document.getElementById('clear').addEventListener('click', () => { qEl.value=''; ansEl.innerHTML=''; ctxEl.innerHTML=''; statusEl.textContent='Cleared.'; });
    async function ask(){
      const q = (qEl.value||'').trim(); if(!q){ statusEl.textContent='Enter a question'; return; }
      const body = {
        q,
        k: Math.min(Math.max(parseInt(kEl.value||'6',10),1),20),
        entity_type: (entEl.value||'').trim()||null,
        scope_id: scopeCtl.get()||null,
        model: (mdlEl.value||'').trim()||null,
      };
      statusEl.textContent='Thinking…'; ansEl.innerHTML=''; ctxEl.innerHTML='';
      try{
        const resp = await fetch('/assist/answer', { method:'POST', headers:{ 'Content-Type':'application/json' }, body: JSON.stringify(body) });
        if(!resp.ok) throw new Error('HTTP '+resp.status);
        const data = await resp.json();
        ansEl.innerHTML = '<div class="sum">Model: '+(data.model||'')+'</div>' + '<pre>'+escapeHtml(data.answer||'')+'</pre>';
        const ctx = data.contexts||[];
        if(ctx.length){
          const list = ctx.map(c => '<li>'+c.entity_type+' • '+(c.title||c.entity_id||'')+' • score '+(c.score?.toFixed?c.score.toFixed(3):c.score)+'</li>').join('');
          ctxEl.innerHTML = '<div class="sum">Contexts: '+ctx.length+'</div><ul style="margin:6px 0 0 18px">'+list+'</ul>';
        } else {
          ctxEl.innerHTML = '<div class="sum">Contexts: 0</div>';
        }
        statusEl.textContent='Done.';
      }catch(err){ statusEl.textContent='Error: '+err.message; }
    }
    function escapeHtml(s){ return (s||'').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
  </script>
</body>
</html>""")


# ---------------------------
# CID Dashboard (shortcuts for specific customer)
# ---------------------------

@router.get("/cid-dashboard", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def cid_dashboard(request: Request, customer_id: str):
    """Dashboard showing all shortcuts and analytics links for a specific Customer ID."""
    from datetime import date
    today = date.today()
    year_start = f"{today.year}-01-01"
    today_iso = today.isoformat()
    
    return HTMLResponse(f"""<!doctype html>
<html lang='en'>
<head>
  <meta charset='utf-8'/>
  <title>CID Dashboard - {customer_id}</title>
  <meta name='viewport' content='width=device-width,initial-scale=1'/>
  <style>
    :root {{
      --bg: #f9fafb; --card-bg: #fff; --border: #e5e7eb; --text: #111827; --muted: #6b7280; --link: #2563eb;
    }}
    * {{ box-sizing:border-box; }}
    body {{ font-family:system-ui,-apple-system,sans-serif; margin:0; padding:20px; background:var(--bg); color:var(--text); line-height:1.5; }}
    .container {{ max-width:1000px; margin:0 auto; }}
    h1 {{ margin:0 0 8px; font-size:24px; font-weight:600; }}
    .subtitle {{ color:var(--muted); font-size:14px; margin-bottom:24px; }}
    .card {{ background:var(--card-bg); border:1px solid var(--border); border-radius:12px; padding:20px; margin-bottom:16px; }}
    .card h2 {{ margin:0 0 12px; font-size:18px; font-weight:600; }}
    .card ul {{ margin:0; padding-left:20px; }}
    .card li {{ margin:6px 0; }}
    .card a {{ color:var(--link); text-decoration:none; }}
    .card a:hover {{ text-decoration:underline; }}
    .back-btn {{ display:inline-block; padding:8px 16px; background:#6b7280; color:#fff; border-radius:6px; text-decoration:none; margin-bottom:16px; }}
    .back-btn:hover {{ background:#4b5563; }}
  </style>
</head>
<body>
  <div class='container'>
    <a href='/misc' class='back-btn'>← Back to Dashboard</a>
    <h1>Customer Dashboard</h1>
    <div class='subtitle'>Customer ID: <strong>{customer_id}</strong></div>

    <div class='card'>
      <h2>Reporting Endpoints</h2>
      <ul>
        <li><a href='/ads/report-30d?customer_id={customer_id}' target='_blank'>30-day Campaign Performance (JSON)</a></li>
        <li><a href='/ads/report-ytd?customer_id={customer_id}' target='_blank'>YTD Aggregate (JSON)</a></li>
        <li><a href='/ads/report-ytd-daily?customer_id={customer_id}&source=auto' target='_blank'>YTD Daily (DB auto, JSON)</a></li>
        <li><a href='/ads/report-ytd-daily?customer_id={customer_id}&source=auto&format=csv' target='_blank'>YTD Daily (DB auto, CSV)</a></li>
        <li><a href='/ads/keyword-ideas?customer_id={customer_id}&seed_keywords=example' target='_blank'>Keyword Ideas (JSON)</a></li>
      </ul>
    </div>

    <div class='card'>
      <h2>ETL Endpoints</h2>
      <ul>
        <li><a href='/etl/missing-days?customer_id={customer_id}&start={year_start}&end={today_iso}&level=campaign' target='_blank'>ETL Missing Days (campaign level)</a></li>
        <li><a href='/etl/missing-days?customer_id={customer_id}&start={year_start}&end={today_iso}&level=multi' target='_blank'>ETL Missing Days (multi-level)</a></li>
      </ul>
    </div>

    <div class='card'>
      <h2>Analytics Dashboards</h2>
      <ul>
        <li><a href='/misc/analytics-mtd?customer_id={customer_id}' target='_blank'>MTD Dashboard</a></li>
        <li><a href='/misc/analytics-ytd-daily?customer_id={customer_id}' target='_blank'>YTD Daily Dashboard</a></li>
        <li><a href='/misc/analytics-keyword-ideas?customer_id={customer_id}' target='_blank'>Keyword Ideas Dashboard</a></li>
        <li><a href='/misc/analytics-etl?customer_id={customer_id}' target='_blank'>ETL Runner Dashboard</a></li>
      </ul>
    </div>

    <div class='card'>
      <h2>Quick Actions</h2>
      <ul>
        <li><a href='/ads/customers?customer_id={customer_id}' target='_blank'>List Child Accounts (JSON)</a></li>
        <li><a href='/ads/active-accounts?customer_id={customer_id}' target='_blank'>Active Accounts (JSON)</a></li>
      </ul>
    </div>
  </div>
</body>
</html>""")


# ---------------------------
# Agents Proposals Management UI
# ---------------------------

@router.get("/agents", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def agents_console(request: Request):
    """UI to list proposals and take actions (approve/reject/execute/measure)."""
    return HTMLResponse("""<!doctype html>
<html lang='en'>
<head>
  <meta charset='utf-8'/>
  <title>Agents Proposals</title>
  <meta name='viewport' content='width=device-width,initial-scale=1'/>
  <style>
    body{margin:0;font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial;background:#0b1220;color:#e6edf3}
    header{padding:14px 18px;background:#0f172a;border-bottom:1px solid #1f2937;display:flex;gap:14px;align-items:center}
    a{color:#93c5fd;text-decoration:none}a:hover{text-decoration:underline}
    .chip{background:#111827;border:1px solid #1f2937;border-radius:12px;padding:6px 12px;font-size:13px}
    main{max-width:1200px;margin:18px auto;padding:0 18px}
    .row{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:12px}
    input,select{background:#0b1220;color:#e6edf3;border:1px solid #1f2937;border-radius:8px;padding:6px 8px}
    button{background:#111827;color:#e6edf3;border:1px solid #1f2937;border-radius:8px;padding:6px 12px;cursor:pointer}
    button:hover{background:#1e293b}
    table{width:100%;border-collapse:collapse;font-size:12px;margin-top:10px}
    th,td{padding:6px 8px;border-bottom:1px solid #1f2937;text-align:left}
    .pill{display:inline-block;background:#111827;border:1px solid #1f2937;border-radius:10px;padding:4px 8px;font-size:11px;margin:2px}
    .ok{color:#22c55e}.err{color:#f87171}.warn{color:#fbbf24}
    .notes{width:200px}
  </style>
</head>
<body>
  <header>
    <div class='chip'>🤖 Agents — Proposals</div>
    <a class='chip' href='/misc/dashboard'>← Dashboard</a>
  </header>
  <main>
    <div class='row'>
      <input id='scopeId' placeholder='scope_id (CID, optional)' style='min-width:220px'>
      <input id='agent' placeholder='agent id (optional)' style='min-width:200px'>
      <select id='status'>
        <option value=''>any status</option>
        <option>proposed</option>
        <option>approved</option>
        <option>rejected</option>
        <option>executed</option>
        <option>measured</option>
      </select>
      <button id='load'>Load</button>
      <button id='bulkApprove'>Approve all filtered</button>
    </div>
    <div id='summary' style='margin-bottom:8px'></div>
    <div style='overflow:auto; max-height:70vh'>
      <table>
        <thead>
          <tr><th>ID</th><th>ts</th><th>agent</th><th>scope_id</th><th>type</th><th>status</th><th>conf</th><th>rationale/payload</th><th>notes</th><th>actions</th></tr>
        </thead>
        <tbody id='rows'></tbody>
      </table>
    </div>
    <h3 style='margin-top:16px'>Activity Log</h3>
    <div class='row'>
      <input id='logScope' placeholder='scope_id (optional)' style='min-width:220px'>
      <button id='loadLog'>Load Log</button>
    </div>
    <div style='overflow:auto; max-height:40vh'>
      <table>
        <thead><tr><th>ID</th><th>ts</th><th>proposal_id</th><th>actor</th><th>action</th><th>notes</th></tr></thead>
        <tbody id='logRows'></tbody>
      </table>
    </div>
  </main>
  <script type='module'>
    import { attachCID } from '/misc/cid.js';
    const scopeCtl = attachCID(document.getElementById('scopeId'), { onEnter: () => load() });
    attachCID(document.getElementById('logScope'));
    const agentEl = document.getElementById('agent');
    const statusEl = document.getElementById('status');
    const rowsEl = document.getElementById('rows');
    const summaryEl = document.getElementById('summary');
    const bulkBtn = document.getElementById('bulkApprove');
    const logRows = document.getElementById('logRows');
    document.getElementById('load').addEventListener('click', load);
    document.getElementById('loadLog').addEventListener('click', loadLog);
    bulkBtn.addEventListener('click', bulkApprove);
    let page=0, pageSize=50, total=0;
    async function load(){
      const params = new URLSearchParams();
      const scope = scopeCtl.get(); if(scope) params.set('scope_id', scope);
      if(agentEl.value.trim()) params.set('agent', agentEl.value.trim());
      if(statusEl.value) params.set('status', statusEl.value);
      params.set('limit', String(pageSize)); params.set('offset', String(page*pageSize));
      const resp = await fetch('/agents/proposals?'+params.toString());
      if(!resp.ok){ rowsEl.innerHTML='<tr><td colspan=10>HTTP '+resp.status+'</td></tr>'; return; }
      const data = await resp.json(); total=data.total||0;
      summaryEl.innerHTML = '<span class="pill">Rows: '+(data.items?.length||0)+' / '+total+'</span>' + (statusEl.value? '<span class="pill">Status: '+statusEl.value+'</span>':'' ) + (agentEl.value? '<span class="pill">Agent: '+agentEl.value+'</span>':'' ) + ' ' + pager();
      rowsEl.innerHTML='';
      (data.items||[]).forEach(r => {
        const tr = document.createElement('tr');
        const notesInp = document.createElement('input'); notesInp.className='notes'; notesInp.placeholder='notes (optional)';
        const actTd = document.createElement('td');
        ['approve','reject','execute','measure'].forEach(a=>{
          const b=document.createElement('button'); b.textContent=a; b.style.marginRight='6px'; b.onclick=()=>decide(r.id,a,notesInp,tr); actTd.appendChild(b);
        });
        const expand = document.createElement('details'); const sum=document.createElement('summary'); sum.textContent='view'; expand.appendChild(sum); const box=document.createElement('div'); box.style.padding='6px'; expand.appendChild(box);
        tr.innerHTML = '<td>'+r.id+'</td>' + '<td>'+ (r.ts||'') +'</td>' + '<td>'+ (r.agent||'') +'</td>' + '<td>'+ (r.scope_id||'') +'</td>' + '<td>'+ (r.type||'') +'</td>' + '<td>'+ (r.status||'') +'</td>' + '<td>'+ (r.confidence??'') +'</td>';
        const rpTd = document.createElement('td'); rpTd.appendChild(expand); tr.appendChild(rpTd);
        const notesTd = document.createElement('td'); notesTd.appendChild(notesInp); tr.appendChild(notesTd);
        tr.appendChild(actTd);
        rowsEl.appendChild(tr);
        // load rationale/payload on demand
        expand.addEventListener('toggle', async () => {
          if(expand.open){
            const resp = await fetch('/agents/proposals/'+r.id);
            if(!resp.ok){ box.textContent='Failed to load details (HTTP '+resp.status+')'; return; }
            const d = await resp.json();
            box.innerHTML = '<div style="font-size:12px;color:#94a3b8">rationale</div>'+
                            '<pre>'+escapeHtml(d.rationale||'')+'</pre>'+
                            '<div style="font-size:12px;color:#94a3b8">payload</div>'+
                            '<pre>'+escapeHtml(JSON.stringify(d.payload,null,2))+'</pre>';
          }
        });
      });
    }
    function pager(){
      const pages = Math.ceil(total/pageSize)||1; const cur=page+1;
      return '<span class="pill">Page '+cur+' / '+pages+'</span>' + (page>0? ' <button id="prevPg">Prev</button>':'') + (cur<pages? ' <button id="nextPg">Next</button>':'');
    }
    summaryEl.addEventListener('click', (e)=>{
      if(e.target.id==='prevPg'){ page=Math.max(0,page-1); load(); }
      if(e.target.id==='nextPg'){ page=page+1; load(); }
    });
    async function bulkApprove(){
      const params = new URLSearchParams();
      const scope = scopeCtl.get(); if(scope) params.set('scope_id', scope);
      if(agentEl.value.trim()) params.set('agent', agentEl.value.trim());
      params.set('status', 'proposed');
      const resp = await fetch('/agents/proposals/bulk-decision?action=approve&'+params.toString(), { method:'POST' });
      if(resp.ok){ load(); } else { alert('Bulk failed: HTTP '+resp.status); }
    }
    async function loadLog(){
      const scope=(document.getElementById('logScope').value||'').trim();
      const q = scope? ('?scope_id='+encodeURIComponent(scope)) : '';
      const resp = await fetch('/agents/decisions'+q);
      if(!resp.ok){ logRows.innerHTML='<tr><td colspan=6>HTTP '+resp.status+'</td></tr>'; return; }
      const data = await resp.json();
      logRows.innerHTML='';
      (data.items||[]).forEach(d=>{
        const tr=document.createElement('tr');
        tr.innerHTML='<td>'+d.id+'</td><td>'+d.ts+'</td><td>'+d.proposal_id+'</td><td>'+d.actor+'</td><td>'+d.action+'</td><td>'+(d.notes||'')+'</td>';
        logRows.appendChild(tr);
      });
    }
    function escapeHtml(s){ return (s||'').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
    async function decide(id, action, notesInp, tr){
      try{
        const body = { action, actor: 'ui', notes: (notesInp.value||'')||null };
        const resp = await fetch('/agents/proposals/'+id+'/decision', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
        if(!resp.ok) throw new Error('HTTP '+resp.status);
        const data = await resp.json();
        // Update status cell (6th td index 5)
        tr.children[5].textContent = data.status || tr.children[5].textContent;
        notesInp.value='';
      }catch(err){ alert('Failed: '+err.message); }
    }
    load();
  </script>
</body>
</html>""")
