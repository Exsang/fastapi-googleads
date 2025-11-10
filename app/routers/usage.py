from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
import html
from ..deps.auth import require_auth
from ..services.usage_log import read_usage_log, usage_summary, quota_usage_summary, prune_quota_usage_older_than

router = APIRouter(
    prefix="/ads", tags=["usage"], dependencies=[Depends(require_auth)])


def _wants_html(request: Request) -> bool:
    """Return True if client requested HTML via Accept header or query flags."""
    accept = (request.headers.get("accept")
              or request.headers.get("Accept") or "").lower()
    qp = request.query_params
    return (
        "text/html" in accept
        or qp.get("format", "").lower() == "html"
        or qp.get("ui", "").lower() in ("1", "true", "yes")
        or qp.get("html", "").lower() in ("1", "true", "yes")
    )


@router.get("/usage-log")
def get_usage_log(request: Request, limit: int = 100, offset: int = 0, provider: str | None = None, metric: str | None = None, scope_id: str | None = None, endpoint: str | None = None):
    rows = read_usage_log(limit, offset, provider=provider,
                          metric=metric, scope_id=scope_id, endpoint_contains=endpoint)
    if not _wants_html(request):
        return {"count": len(rows), "rows": rows}
    # Render HTML table similar to dashboard style

    def cell(v: object) -> str:
        return html.escape("" if v is None else str(v))
    tr_rows = []
    for r in rows:
        tr_rows.append(
            f"<tr>"
            f"<td>{cell(r.get('ts'))}</td>"
            f"<td>{cell(r.get('scope_id'))}</td>"
            f"<td>{cell(r.get('endpoint'))}</td>"
            f"<td>{cell(r.get('request_type'))}</td>"
            f"<td style='text-align:right'>{cell(r.get('operations'))}</td>"
            f"<td class='muted'>{cell(r.get('request_id'))}</td>"
            f"</tr>"
        )
    # Simple in-page filter form (querystring based)
    html_doc = f"""<!doctype html>
<html><head>
    <meta charset='utf-8'/><title>API Usage Log</title>
    <meta name='viewport' content='width=device-width,initial-scale=1'/>
    <style>
        :root {{ --bg:#0b1220; --fg:#e6edf3; --muted:#94a3b8; --card:#111827; --border:#1f2937; --accent:#93c5fd; }}
        body{{margin:0;background:var(--bg);color:var(--fg);font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial}}
        header{{padding:14px 18px;background:#0f172a;border-bottom:1px solid var(--border);display:flex;gap:12px;align-items:center;flex-wrap:wrap}}
        .chip{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:6px 12px;font-size:13px}}
        a{{color:var(--accent);text-decoration:none}} a:hover{{text-decoration:underline}}
        main{{max-width:1100px;margin:20px auto;padding:0 16px}}
        table{{width:100%;border-collapse:collapse;font-size:13px}}
        th,td{{padding:6px 8px;border-bottom:1px solid var(--border);text-align:left}}
        th{{color:var(--muted);font-weight:600}}
        .muted{{color:var(--muted);}}
    </style>
    </head><body>
        <header>
            <div class='chip'>📜 API Usage Log</div>
            <a class='chip' href='/misc/dashboard'>← Dashboard</a>
            </header>
        <main>
                <form method='get' style='margin:0 0 14px;display:flex;flex-wrap:wrap;gap:8px;align-items:flex-end'>
                    <div style='display:flex;flex-direction:column;gap:4px'>
                        <label style='font-size:11px;color:var(--muted)'>Provider</label>
                        <input name='provider' value='{html.escape(provider or "")}' placeholder='e.g. google_ads' style='background:#111827;color:#e6edf3;border:1px solid var(--border);border-radius:8px;padding:6px 8px;'>
                    </div>
                    <div style='display:flex;flex-direction:column;gap:4px'>
                        <label style='font-size:11px;color:var(--muted)'>Metric</label>
                        <input name='metric' value='{html.escape(metric or "")}' placeholder='e.g. requests' style='background:#111827;color:#e6edf3;border:1px solid var(--border);border-radius:8px;padding:6px 8px;'>
                    </div>
                    <div style='display:flex;flex-direction:column;gap:4px'>
                        <label style='font-size:11px;color:var(--muted)'>Scope ID</label>
                        <input name='scope_id' value='{html.escape(scope_id or "")}' placeholder='e.g. 7414394764' style='background:#111827;color:#e6edf3;border:1px solid var(--border);border-radius:8px;padding:6px 8px;'>
                    </div>
                    <div style='display:flex;flex-direction:column;gap:4px'>
                        <label style='font-size:11px;color:var(--muted)'>Endpoint contains</label>
                        <input name='endpoint' value='{html.escape(endpoint or "")}' placeholder='e.g. /ads/' style='background:#111827;color:#e6edf3;border:1px solid var(--border);border-radius:8px;padding:6px 8px;'>
                    </div>
                    <div style='display:flex;flex-direction:column;gap:4px'>
                        <label style='font-size:11px;color:var(--muted)'>Limit</label>
                        <input name='limit' value='{limit}' style='width:90px;background:#111827;color:#e6edf3;border:1px solid var(--border);border-radius:8px;padding:6px 8px;'>
                    </div>
                    <div style='display:flex;flex-direction:column;gap:4px'>
                        <label style='font-size:11px;color:var(--muted)'>Offset</label>
                        <input name='offset' value='{offset}' style='width:90px;background:#111827;color:#e6edf3;border:1px solid var(--border);border-radius:8px;padding:6px 8px;'>
                    </div>
                    <div style='display:flex;flex-direction:column;gap:4px'>
                        <label style='font-size:11px;color:var(--muted)'>&nbsp;</label>
                        <button style='background:#1e293b;color:#e6edf3;border:1px solid var(--border);border-radius:8px;padding:8px 14px;cursor:pointer'>Apply</button>
                    </div>
                    <div style='display:flex;flex-direction:column;gap:4px'>
                        <label style='font-size:11px;color:var(--muted)'>&nbsp;</label>
                        <a href='/ads/usage-log?format=html' style='background:#111827;color:#93c5fd;border:1px solid var(--border);border-radius:8px;padding:8px 14px;text-decoration:none;display:inline-block'>Reset</a>
                    </div>
                </form>
            <table>
                <thead><tr><th>Timestamp</th><th>Scope</th><th>Endpoint</th><th>Type</th><th style='text-align:right'>Ops</th><th>Request ID</th></tr></thead>
                <tbody>
                    {''.join(tr_rows) if tr_rows else "<tr><td colspan='6' class='muted'>No rows</td></tr>"}
                </tbody>
            </table>
        </main>
    </body></html>"""
    return HTMLResponse(html_doc)


@router.get("/usage-summary")
def get_usage_summary(request: Request):
    s = usage_summary()
    if not _wants_html(request):
        return s

    def fmt(n):
        try:
            return f"{int(n):,}"
        except Exception:
            try:
                return f"{float(n):,.2f}"
            except Exception:
                return html.escape(str(n))
    cards = [
        ("API calls (today)", s.get("today_usage_rows")),
        ("API calls (all time)", s.get("total_usage_rows")),
        ("GET requests (today)", s.get("today_get_requests")),
        ("Operations (today)", s.get("today_operations")),
    ]
    html_doc = f"""<!doctype html>
<html><head>
    <meta charset='utf-8'/><title>API Usage Summary</title>
    <meta name='viewport' content='width=device-width,initial-scale=1'/>
    <style>
        :root {{ --bg:#0b1220; --fg:#e6edf3; --muted:#94a3b8; --card:#111827; --border:#1f2937; --accent:#93c5fd; }}
        body{{margin:0;background:var(--bg);color:var(--fg);font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial}}
        header{{padding:14px 18px;background:#0f172a;border-bottom:1px solid var(--border);display:flex;gap:12px;align-items:center;flex-wrap:wrap}}
        .chip{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:6px 12px;font-size:13px}}
        a{{color:var(--accent);text-decoration:none}} a:hover{{text-decoration:underline}}
        main{{max-width:1100px;margin:20px auto;padding:0 16px}}
        .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}}
        .card{{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:14px}}
        .title{{color:var(--muted);font-size:12px}}
        .value{{font-size:24px;font-weight:700;margin-top:4px}}
    </style>
    </head><body>
        <header>
            <div class='chip'>📊 API Usage Summary</div>
            <a class='chip' href='/misc/dashboard'>← Dashboard</a>
        </header>
        <main>
            <div class='grid'>
                {''.join(f"<div class='card'><div class='title'>{html.escape(k)}</div><div class='value'>{fmt(v)}</div></div>" for k, v in cards)}
            </div>
            <div class='card' style='margin-top:14px'>
                <div class='title'>Caps</div>
                <div style='margin-top:6px'>GET cap: {fmt(s.get('get_cap'))} • Ops cap: {fmt(s.get('ops_cap'))}</div>
            </div>
        </main>
    </body></html>"""
    return HTMLResponse(html_doc)


@router.get("/quota-summary")
def get_quota_summary(request: Request, provider: str | None = None):
    q = quota_usage_summary(provider)
    if not _wants_html(request):
        return q
    totals = q.get("totals", [])
    todays = q.get("today", [])

    def tr(rows):
        if not rows:
            return "<tr><td colspan='3' class='muted'>No data</td></tr>"
        out = []
        for r in rows:
            out.append(
                f"<tr><td>{html.escape(r.get('provider', ''))}</td><td>{html.escape(r.get('metric', ''))}</td><td style='text-align:right'>{html.escape(str(r.get('total') or 0))}</td></tr>")
        return ''.join(out)
    subtitle = f"Provider filter: <b>{html.escape(provider or '—')}</b>"
    html_doc = f"""<!doctype html>
<html><head>
    <meta charset='utf-8'/><title>Quota Usage Summary</title>
    <meta name='viewport' content='width=device-width,initial-scale=1'/>
    <style>
        :root {{ --bg:#0b1220; --fg:#e6edf3; --muted:#94a3b8; --card:#111827; --border:#1f2937; --accent:#93c5fd; }}
        body{{margin:0;background:var(--bg);color:var(--fg);font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial}}
        header{{padding:14px 18px;background:#0f172a;border-bottom:1px solid var(--border);display:flex;gap:12px;align-items:center;flex-wrap:wrap}}
        .chip{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:6px 12px;font-size:13px}}
        a{{color:var(--accent);text-decoration:none}} a:hover{{text-decoration:underline}}
        main{{max-width:1100px;margin:20px auto;padding:0 16px}}
        h3{{margin:10px 0 6px}}
        .muted{{color:var(--muted)}}
        table{{width:100%;border-collapse:collapse;font-size:13px}}
        th,td{{padding:6px 8px;border-bottom:1px solid var(--border);text-align:left}}
        th{{color:var(--muted);font-weight:600}}
    </style>
    </head><body>
        <header>
            <div class='chip'>⏳ Quota Usage Summary</div>
            <a class='chip' href='/misc/dashboard'>← Dashboard</a>
        </header>
        <main>
            <div class='muted'>{subtitle}</div>
            <section class='card' style='margin-top:12px;padding:12px;border:1px solid var(--border);border-radius:12px;background:var(--card)'>
                <h3>Totals (all time)</h3>
                <table><thead><tr><th>Provider</th><th>Metric</th><th style='text-align:right'>Total</th></tr></thead>
                <tbody>{tr(totals)}</tbody></table>
            </section>
            <section class='card' style='margin-top:12px;padding:12px;border:1px solid var(--border);border-radius:12px;background:var(--card)'>
                <h3>Today</h3>
                <table><thead><tr><th>Provider</th><th>Metric</th><th style='text-align:right'>Total</th></tr></thead>
                <tbody>{tr(todays)}</tbody></table>
            </section>
        </main>
    </body></html>"""
    return HTMLResponse(html_doc)


@router.post("/quota-prune")
def post_quota_prune(days: int = 90):
    deleted = prune_quota_usage_older_than(days)
    return {"deleted": deleted, "days": days}
