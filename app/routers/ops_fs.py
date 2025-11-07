# app/routers/ops_fs.py
from __future__ import annotations

import base64
import fnmatch
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse

# ---- Auth dependency (reuse your existing key check) -------------------------
try:
    from app.deps.auth import require_api_key  # type: ignore
except Exception:  # pragma: no cover
    def require_api_key():
        return None

router = APIRouter(prefix="/ops", tags=["ops"])

# ---- Tunables via env --------------------------------------------------------
FS_ROOT = Path(os.getenv("FS_ROOT", ".")).resolve()
FS_MAX_BYTES = int(os.getenv("FS_MAX_BYTES", "500000"))  # cap reads (500 KB)
FS_LIST_MAX = int(os.getenv("FS_LIST_MAX", "2000"))      # cap entries returned

# Known-safe text extensions for /ops/code
ALLOWED_TEXT_EXTS = {
    ".py", ".ts", ".tsx", ".js", ".jsx",
    ".json", ".md", ".txt", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".env",
    ".sql", ".csv", ".html", ".css",
}

# Ignore globs to keep responses small & safe
DEFAULT_IGNORE = [
    ".git*", ".venv*", "venv*", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "node_modules", "dist", "build",
    "*.pyc", "*.pyo", "*.pyd", "*.so", "*.dll", "*.dylib",
    "*.png", "*.jpg", "*.jpeg", "*.gif", "*.ico", "*.pdf",
    "*.zip", "*.tar", "*.gz", "*.xz", "*.7z", "*.parquet", "*.db",
]


# ---- Helpers -----------------------------------------------------------------

def _inside(root: Path, p: Path) -> bool:
    """True if p is inside root after resolving symlinks."""
    try:
        return os.path.commonpath([str(root), str(p)]) == str(root)
    except Exception:
        return False


def _safe_join(root: Path, relpath: str) -> Path:
    # Resolve with strict checks but allow non-existing final for consistency
    candidate = (root / relpath).resolve()
    if not _inside(root, candidate):
        raise HTTPException(status_code=400, detail="Path escapes FS_ROOT")
    return candidate


def _is_ignored(path: Path, ignore_globs: List[str]) -> bool:
    # Match both name and relative path against globs
    rel = str(path)
    name = path.name
    for pat in ignore_globs:
        if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(rel, pat):
            return True
    return False


def _is_text_file(path: Path) -> bool:
    return path.suffix.lower() in ALLOWED_TEXT_EXTS


def _read_utf8_text(path: Path, max_bytes: int, errors: str = "strict") -> str:
    size = path.stat().st_size
    if size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({size} bytes > {max_bytes})",
        )
    try:
        return path.read_text(encoding="utf-8", errors=errors)
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=415,
            detail="Not UTF-8 text; use /ops/blob for base64 bytes.",
        )


def _walk_limited(
    root: Path,
    target: Path,
    depth: int,
    include_files: bool,
    include_dirs: bool,
    include_hidden: bool,
    ignore_globs: List[str],
    limit: int,
    marker: Optional[str],
) -> Tuple[Dict[str, Any], Optional[str]]:
    """
    Walk a directory with a hard limit on returned entries.
    Supports a 'marker' (path) to continue pagination.
    Returns (tree, next_marker).
    """
    # Normalize marker
    marker_seen = marker is None
    returned = 0
    next_marker: Optional[str] = None

    def walk_dir(p: Path, d: int) -> Dict[str, Any]:
        nonlocal returned, next_marker, marker_seen

        node: Dict[str, Any] = {
            "name": p.name if p != root else "/",
            "path": "" if p == root else str(p.relative_to(root)),
            "type": "dir",
            "children": [],
        }
        if d < 0:
            return node

        try:
            entries = sorted(
                p.iterdir(),
                key=lambda q: (q.is_file(), q.name.lower())  # dirs first
            )
        except PermissionError:
            node["error"] = "Permission denied"
            return node

        for e in entries:
            rel = str(e.relative_to(root))
            # Pagination marker handling
            if not marker_seen:
                if rel == marker:
                    marker_seen = True
                continue

            # Hidden filtering
            if not include_hidden and e.name.startswith("."):
                continue

            # Ignore patterns
            if _is_ignored(Path(rel), ignore_globs):
                continue

            # Stop when hitting the limit
            if returned >= limit:
                next_marker = rel
                break

            if e.is_dir():
                if include_dirs:
                    child = walk_dir(e, d - 1)
                    node["children"].append(child)
                    returned += 1
            else:
                if include_files:
                    node["children"].append({
                        "name": e.name,
                        "path": rel,
                        "type": "file",
                        "size": e.stat().st_size,
                        "ext": e.suffix,
                        "is_text": _is_text_file(e),
                    })
                    returned += 1

        return node

    return walk_dir(target, depth), next_marker


# ---- Endpoints ---------------------------------------------------------------

@router.get(
    "/fs",
    response_class=JSONResponse,
    summary="List directory tree (read-only, paginated)",
)
def list_tree(
    path: str = Query("", description="Path relative to FS_ROOT"),
    depth: int = Query(2, ge=0, le=10, description="Directory recursion depth"),
    include_files: bool = Query(True),
    include_dirs: bool = Query(True),
    include_hidden: bool = Query(False),
    limit: int = Query(500, ge=1, le=FS_LIST_MAX, description="Max entries returned"),
    marker: Optional[str] = Query(None, description="Resume listing after this path"),
    ignore: Optional[List[str]] = Query(None, description="Extra ignore globs"),
    _: Any = Depends(require_api_key),
) -> Dict[str, Any]:
    """
    Lists a directory tree with safety & pagination. If `path` is a file, returns
    lightweight metadata for that file instead.
    """
    root = FS_ROOT
    target = _safe_join(root, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")

    # Build ignore list
    ignore_globs = DEFAULT_IGNORE.copy()
    if ignore:
        ignore_globs.extend(ignore)

    # If target is file, short-circuit
    if target.is_file():
        return {
            "root": str(root),
            "type": "file",
            "path": str(target.relative_to(root)),
            "size": target.stat().st_size,
            "ext": target.suffix,
            "is_text": _is_text_file(target),
        }

    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Not a directory")

    tree, next_marker = _walk_limited(
        root=root,
        target=target,
        depth=depth,
        include_files=include_files,
        include_dirs=include_dirs,
        include_hidden=include_hidden,
        ignore_globs=ignore_globs,
        limit=limit,
        marker=marker,
    )

    return {"root": str(root), "tree": tree, "next_marker": next_marker}


@router.get(
    "/code",
    response_class=PlainTextResponse,
    summary="Get a UTF-8 text file (safe extensions only)",
)
def get_code(
    path: str = Query(..., description="Text file path relative to FS_ROOT"),
    errors: str = Query("strict", regex="^(strict|ignore|replace)$",
                        description="UTF-8 decode policy"),
    _: Any = Depends(require_api_key),
) -> str:
    """
    Returns file contents as text/plain for known-safe text extensions.
    For non-UTF8 files, use /ops/blob.
    """
    target = _safe_join(FS_ROOT, path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if not _is_text_file(target):
        raise HTTPException(status_code=415, detail="Not a recognized text file type")
    return _read_utf8_text(target, FS_MAX_BYTES, errors=errors)


@router.get(
    "/blob",
    response_class=JSONResponse,
    summary="Get base64 bytes for any file (size-limited)",
)
def get_blob(
    path: str = Query(..., description="Any file path relative to FS_ROOT"),
    _: Any = Depends(require_api_key),
) -> Dict[str, Any]:
    """
    Returns base64-encoded bytes for a file, enforcing FS_MAX_BYTES.
    Useful when /ops/code fails due to encoding or disallowed extension.
    """
    target = _safe_join(FS_ROOT, path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    size = target.stat().st_size
    if size > FS_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({size} bytes > {FS_MAX_BYTES})",
        )
    return {
        "path": str(target.relative_to(FS_ROOT)),
        "size": size,
        "base64": base64.b64encode(target.read_bytes()).decode("ascii"),
    }
