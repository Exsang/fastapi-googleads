import csv
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from ..settings import settings

LOG_PATH = Path("api_usage_log.csv")

def log_api_usage(*, scope_id: str, request_id: str | None, endpoint: str, request_type: str, operations: int = 0) -> None:
    row = [datetime.utcnow().isoformat(), scope_id, request_id or "", endpoint, request_type, str(operations)]
    with LOG_PATH.open("a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(row)

def read_usage_log(limit: int, offset: int):
    if not LOG_PATH.exists():
        return {"total": 0, "rows": [], "note": "No usage yet."}
    rows = []
    with LOG_PATH.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) == 4:
                ts, scope, req_id, _count = row
                rows.append({"timestamp_utc": ts, "scope_id": scope, "request_id": req_id, "endpoint": "(legacy)", "request_type": "unknown", "operations": 0})
            else:
                ts, scope, req_id, endpoint, req_type, ops = (row + ["", "", "", "", ""])[:6]
                rows.append({"timestamp_utc": ts, "scope_id": scope, "request_id": req_id, "endpoint": endpoint, "request_type": req_type, "operations": int(ops) if ops.isdigit() else 0})
    rows.sort(key=lambda r: r["timestamp_utc"], reverse=True)
    return {"total": len(rows), "limit": limit, "offset": offset, "rows": rows[offset: offset + limit]}

def usage_summary():
    if not LOG_PATH.exists():
        return {"by_day": {}, "total_calls": 0, "total_gets": 0, "total_ops": 0}
    by_day = defaultdict(lambda: {"calls": 0, "gets": 0, "ops": 0})
    total_calls = total_gets = total_ops = 0
    with LOG_PATH.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            ts = row[0] if len(row) > 0 else ""
            req_type = row[4] if len(row) > 4 else "unknown"
            ops = int(row[5]) if len(row) > 5 and row[5].isdigit() else 0
            try:
                day = datetime.fromisoformat(ts).date().isoformat()
            except ValueError:
                continue
            by_day[day]["calls"] += 1
            if req_type == "get":
                by_day[day]["gets"] += 1
            by_day[day]["ops"] += ops
            total_calls += 1
            total_ops += ops
            if req_type == "get":
                total_gets += 1
    by_day_sorted = dict(sorted(by_day.items(), key=lambda kv: kv[0], reverse=True))
    return {"by_day": by_day_sorted, "total_calls": total_calls, "total_gets": total_gets, "total_ops": total_ops}

def dashboard_stats(default_mcc: str) -> dict:
    from ..services.google_ads import google_ads_client
    stats = {
        "total_usage_rows": 0, "today_usage_rows": 0, "today_get_requests": 0, "today_operations": 0,
        "accessible_customers": None, "active_children_under_mcc": None,
        "get_cap": GET_CAP, "ops_cap": OPS_CAP,
    }
    # CSV pass (best effort)
    if LOG_PATH.exists():
        try:
            today = datetime.utcnow().date().isoformat()
            with LOG_PATH.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                total = today_count = today_get = today_ops = 0
                for row in reader:
                    ts = row[0] if len(row) > 0 else ""
                    req_type = row[4] if len(row) > 4 else "unknown"
                    ops = int(row[5]) if len(row) > 5 and row[5].isdigit() else 0
                    total += 1
                    try:
                        d = datetime.fromisoformat(ts).date().isoformat()
                        if d == today:
                            today_count += 1
                            if req_type == "get":
                                today_get += 1
                            today_ops += ops
                    except ValueError:
                        continue
            stats.update({
                "total_usage_rows": total,
                "today_usage_rows": today_count,
                "today_get_requests": today_get,
                "today_operations": today_ops,
            })
        except Exception:
            pass
    # Live Ads (best effort)
    try:
        client = google_ads_client()
        svc = client.get_service("CustomerService")
        resp = svc.list_accessible_customers()
        stats["accessible_customers"] = len(resp.resource_names)

        ga = client.get_service("GoogleAdsService")
        query = """
          SELECT customer_client.id
          FROM customer_client
          WHERE customer_client.level = 1
            AND customer_client.status = 'ENABLED'
            AND customer_client.hidden = FALSE
            AND customer_client.manager = FALSE
        """
        rows = ga.search(customer_id=default_mcc, query=query)
        stats["active_children_under_mcc"] = sum(1 for _ in rows)
    except Exception:
        pass
    return stats
