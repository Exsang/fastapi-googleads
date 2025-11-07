# app/routers/ops_code.py
from __future__ import annotations

import base64
import fnmatch
import os
from pathlib import Path
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import PlainTextResponse, JSONResponse

# Reuse your existing API key dependency
try:
    from app.deps.auth import require_api_key  # <- your existing dependency
except Exception:
    # Fallback no-op if import path is different; change to match your project if needed.
    def require_api_key():
        return None

# Optional: pick up settings, with safe defaults
try:
    from app.settings import settings  # if you already have a Settings model
    FS_ROOT = Path(getattr(settings, "FS_ROOT", ".")).resolve()
    FS_MAX_BYTES = int(getattr(settings, "FS_MAX_BYTES", 500_000))  # 500 KB
except Exception:
    FS_ROOT = Path(".").resolve()
    FS_MAX_BYTES = 500_000

ALLOWED_TEXT_EXTS = {
    ".py", ".ts", ".tsx", ".js", ".jsx",
    ".json", ".md", ".txt", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".env",
    ".sql", ".csv", ".html", ".css"
}

DEFAULT_IGNORE = [
    ".git*", ".venv*", "venv*", "__pycache__", ".mypy_cache",
    ".pytest_cache", "node_modules", "dist", "build", ".ruff_cache",
    "*.pyc", "*.pyo", "*.pyd", "*.so", "*.dll", "*.dylib",
    "*.png", "*.jpg", "*.jpeg", "*.gif", "*.ico", "*.pdf",
    "*.zip", "*.tar", "*.gz", "*.xz", "*.7z", "*.parquet", "*.db"
]

router = APIRouter(prefix="/ops", tags=["ops"])


def _is_ignored(name: str, ignore_globs: List[str]) -> bool:
    for pat in ignore_globs:
        if fnmatch.fnmatch(name, pat):
            return True
    return False


def _safe_join(root: Path, user_path: str) -> Path:
    # Prevent path traversal and force everything under FS_ROOT
    cand = (root / user_path).resolve()
    if not str(cand).startswith(str(root)):
        raise HTTPException(status_code=400, detail="Path escapes FS_ROOT")
    return cand


def _is_text_file(path: Path) -> bool:
    return path.suffix.lower() in ALLOWED_TEXT_EXTS


def _read_file_text(path: Path, max_bytes: int) -> str:
    size = path.stat().st_size
    if size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({size} bytes > {max_bytes})"
        )
    try:
        # Try utf-8 first
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Fallback: serve as base64 if not utf-8 decodable
        raw = path.read_bytes()
        if len(raw) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File too large ({len(raw)} bytes > {max_bytes})"
            )
        b64 = base64.b64encode(raw).decode("ascii")
        raise HTTPException(
            status_code=415,
            detail="File is not UTF-8 text; try /ops/blob to get base64 bytes."
        )


@router.get("/fs", response_class=JSONResponse)
def list_tree(
    path: str = Query("", description="Path relative to FS_ROOT"),
    depth: int = Query(2, ge=0, le=10, description="Directory recursion depth"),
    include_files: bool = Query(True),
    include_dirs: bool = Query(True),
    ignore: Optional[List[str]] = Query(None, description="Extra ignore globs"),
    _: Any = Depends(require_api_key),
) -> Dict[str, Any]:
    """
    List a directory tree (read-only). Ignores common build/cache/binary paths.
    """
    root = FS_ROOT
    ignore_globs = DEFAULT_IGNORE.copy()
    if ignore:
        ignore_globs.extend(ignore)

    target = _safe_join(root, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    if target.is_file():
        # If it's a file, return basic file metadata
        return {
            "root": str(root),
            "path": str(target.relative_to(root)),
            "type": "file",
            "size": target.stat().st_size,
            "is_text": _is_text_file(target),
            "ext": target.suffix,
        }

    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Not a directory")

    def walk(p: Path, d: int) -> Dict[str, Any]:
        item: Dict[str, Any] = {
            "name": p.name if p != root else "/",
            "path": str(p.relative_to(root)) if p != root else "",
            "type": "dir",
            "children": [],
        }
        if d < 0:
            return item
        try:
            entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        except PermissionError:
            return {**item, "error": "Permission denied"}

        for e in entries:
            rel = str(e.relative_to(root))
            name = e.name
            if _is_ignored(name, ignore_globs) or _is_ignored(rel, ignore_globs):
                continue
            if e.is_dir():
                if include_dirs:
                    child = walk(e, d - 1)
                    item["children"].append(child)
            else:
                if include_files:
                    item["children"].append({
                        "name": name,
                        "path": rel,
                        "type": "file",
                        "size": e.stat().st_size,
                        "ext": e.suffix,
                        "is_text": _is_text_file(e),
                    })
        return item

    tree = walk(target, depth)
    return {"root": str(root), "tree": tree}


@router.get("/code", response_class=PlainTextResponse)
def get_code(
    path: str = Query(..., description="Path to a *text* file relative to FS_ROOT"),
    _: Any = Depends(require_api_key),
):
    """
    Return file contents as text/plain for known text extensions.
    Blocks binary/large files. For non-UTF8 files, use /ops/blob.
    """
    target = _safe_join(FS_ROOT, path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if not _is_text_file(target):
        raise HTTPException(status_code=415, detail="Not a recognized text file type")
    return _read_file_text(target, FS_MAX_BYTES)


@router.get("/blob", response_class=JSONResponse)
def get_blob(
    path: str = Query(..., description="Path to any file relative to FS_ROOT"),
    _: Any = Depends(require_api_key),
):
    """
    Return base64-encoded bytes for a file (useful when UTF-8 fails).
    Enforces max size.
    """
    target = _safe_join(FS_ROOT, path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    size = target.stat().st_size
    if size > FS_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({size} bytes > {FS_MAX_BYTES})"
        )
    data_b64 = base64.b64encode(target.read_bytes()).decode("ascii")
    return {
        "path": str(target.relative_to(FS_ROOT)),
        "size": size,
        "base64": data_b64,
    }
