# scripts/generate_env_summary.py
"""
Generates or updates the Auto-Generated section in ENVIRONMENT.md with:
- Live FastAPI routes
- Settings snapshot (masked secrets)
- Package versions
- Folder tree
- Git branch + commit
- Route count + namespaces
"""

import os
import re
import sys
import json
import importlib
import subprocess
import textwrap
import datetime as dt
from pathlib import Path
from typing import Any

from fastapi import FastAPI

# ---------- Paths ----------
ROOT = Path(__file__).resolve().parents[1]
ENV_MD = ROOT / "ENVIRONMENT.md"

# ---------- Secret masking ----------
def _mask(v: Any, keep: int = 4) -> Any:
    if v is None:
        return None
    s = str(v)
    return s if len(s) <= keep * 2 else s[:keep] + "…" + s[-keep:]

SENSITIVE_KEYS = {
    "DEV_TOKEN",
    "DASH_API_KEY",
    "GOOGLE_ADS_CLIENT_SECRET",
    "GOOGLE_ADS_REFRESH_TOKEN",
}

# ---------- Load FastAPI app ----------
def load_app() -> FastAPI:
    sys.path.insert(0, str(ROOT))
    mod = importlib.import_module("app.main")

    for attr in ("app", "APP", "api", "API", "application", "APPLICATION"):
        if hasattr(mod, attr):
            obj = getattr(mod, attr)
            if isinstance(obj, FastAPI):
                return obj
            if callable(obj):
                try:
                    maybe = obj()
                    if isinstance(maybe, FastAPI):
                        return maybe
                except TypeError:
                    pass

    for factory in ("create_app", "get_app", "make_app"):
        if hasattr(mod, factory) and callable(getattr(mod, factory)):
            maybe = getattr(mod, factory)()
            if isinstance(maybe, FastAPI):
                return maybe

    raise AttributeError(
        "Could not locate a FastAPI instance in app.main. "
        "Tried app/APP/api/API/application/APPLICATION or a factory like create_app()."
    )

# ---------- Collectors ----------
def get_routes(app: FastAPI):
    rows = []
    for r in app.routes:
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None)
        if not path or not methods:
            continue
        methods_clean = ",".join(sorted(m for m in methods if m not in {"HEAD", "OPTIONS"}))
        name = getattr(r, "name", "")
        rows.append({"path": path, "methods": methods_clean, "name": name})
    rows.sort(key=lambda x: x["path"])
    return rows

def get_settings():
    try:
        mod = importlib.import_module("app.settings")
        keys = [
            "DEFAULT_MCC_ID",
            "LOGIN_CID",
            "DEV_TOKEN",
            "DASH_API_KEY",
        ]
        out = {}
        for k in keys:
            val = getattr(mod, k, None)
            out[k] = _mask(val) if k in SENSITIVE_KEYS else val
        return out
    except Exception:
        return {}

def get_versions():
    def pip_show(pkg: str):
        try:
            res = subprocess.run(
                [sys.executable, "-m", "pip", "show", pkg],
                capture_output=True,
                text=True,
                check=False,
            )
            for line in res.stdout.splitlines():
                if line.startswith("Version:"):
                    return line.split(":", 1)[1].strip()
        except Exception:
            pass
        return None

    pkgs = ["fastapi", "uvicorn", "google-ads", "pydantic"]
    return {p: pip_show(p) for p in pkgs}

def folder_tree(max_depth: int = 2) -> str:
    lines = []

    def walk(p: Path, depth: int = 0):
        if depth > max_depth:
            return
        entries = sorted(
            [
                e
                for e in p.iterdir()
                if not e.name.startswith(".")
                and e.name not in {"__pycache__", "venv", ".venv"}
            ],
            key=lambda x: (x.is_file(), x.name.lower()),
        )
        for e in entries:
            lines.append(("  " * depth) + ("- " + e.name + ("/" if e.is_dir() else "")))
            if e.is_dir():
                walk(e, depth + 1)

    walk(ROOT)
    return "\n".join(lines)

def get_git_info():
    try:
        branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True).strip()
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
        return {"branch": branch, "commit": commit}
    except Exception:
        return None

# ---------- Render ----------
def render(routes, settings, tree, versions, generated_at: str, git: dict | None) -> str:
    def jdump(obj) -> str:
        return json.dumps(obj, indent=2, default=str, ensure_ascii=False)

    api_count = len(routes)
    services = sorted({
        p.split('/')[1]
        for p in [r['path'] for r in routes]
        if p.count('/') >= 2 and not p.startswith(('/docs', '/openapi'))
    })
    service_list = ", ".join(services) if services else "—"
    git_line = f"{git['branch']}@{git['commit']}" if git else "no-git"
    header = (
        f"_Generated at: **{generated_at}**  |  **{git_line}**_\n\n"
        f"**Routes:** {api_count}  •  **Namespaces:** {service_list}\n"
    )

    route_lines = ["| Method(s) | Path | Name |", "|---|---|---|"]
    for r in routes:
        route_lines.append(f"| {r['methods']} | `{r['path']}` | {r['name']} |")
    routes_md = "\n".join(route_lines)

    settings_md = "```\n" + jdump(settings) + "\n```"
    versions_md = "```\n" + jdump(versions) + "\n```"
    tree_md = "```\n" + tree + "\n```"

    return (
        f"{header}\n"
        f"### Routes (live)\n{routes_md}\n\n"
        f"### Settings snapshot (selected)\n{settings_md}\n\n"
        f"### Package versions\n{versions_md}\n\n"
        f"### Folder tree (depth 2)\n{tree_md}"
    )

def replace_auto(md_text: str, new_block: str) -> str:
    start = "<!-- BEGIN AUTO -->"
    end = "<!-- END AUTO -->"
    pattern = re.compile(rf"({re.escape(start)})(.*)({re.escape(end)})", re.DOTALL)

    def _repl(_match: re.Match) -> str:
        return f"{start}\n{new_block}\n{end}"

    if pattern.search(md_text):
        return pattern.sub(_repl, md_text)
    return md_text.rstrip() + f"\n\n{start}\n{new_block}\n{end}\n"

# ---------- Main ----------
def main():
    if not ENV_MD.exists():
        ENV_MD.write_text(
            "# ENVIRONMENT (Single Source of Truth)\n\n"
            "> Keep this file updated. Manual notes go above; the script updates the auto section below.\n\n"
            "## Manual Notes (edit me)\n\n"
            "---\n\n"
            "## Auto-Generated Summary (do not edit below)\n"
            "<!-- BEGIN AUTO -->\n<!-- END AUTO -->\n",
            encoding="utf-8",
        )

    app = load_app()
    routes = get_routes(app)
    settings = get_settings()
    versions = get_versions()
    tree = folder_tree()
    git = get_git_info()
    generated_at = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    block = render(routes, settings, tree, versions, generated_at, git)

    md = ENV_MD.read_text(encoding="utf-8")
    md2 = replace_auto(md, block)
    ENV_MD.write_text(md2, encoding="utf-8")
    print("✅ Updated ENVIRONMENT.md")

if __name__ == "__main__":
    main()
