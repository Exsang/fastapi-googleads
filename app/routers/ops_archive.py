# app/routers/ops_archive.py
from __future__ import annotations

import os
import tarfile
import time
from fnmatch import fnmatch
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

try:
    from app.deps.auth import require_api_key  # type: ignore
except Exception:  # pragma: no cover
    def require_api_key():
        return None

router = APIRouter(prefix="/ops", tags=["ops"])

FS_ROOT = Path(os.getenv("FS_ROOT", ".")).resolve()

DEFAULT_IGNORE = [
    ".git*", ".venv*", "venv*", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "node_modules", "dist", "build",
    "*.pyc", "*.pyo", "*.pyd", "*.so", "*.dll", "*.dylib",
    "*.png", "*.jpg", "*.jpeg", "*.gif", "*.ico", "*.pdf",
    "*.zip", "*.tar", "*.gz", "*.xz", "*.7z", "*.parquet", "*.db",
]

SAFE_TEXT_EXTS = {
    ".py",".ts",".tsx",".js",".jsx",".json",".md",".txt",".yaml",".yml",
    ".toml",".ini",".cfg",".env",".sql",".csv",".html",".css"
}

def _inside(root: Path, p: Path) -> bool:
    try:
        return os.path.commonpath([str(root), str(p)]) == str(root)
    except Exception:
        return False

def _safe_join(root: Path, rel: str) -> Path:
    p = (root / rel).resolve()
    if not _inside(root, p):
        raise HTTPException(status_code=400, detail="Path escapes FS_ROOT")
    return p

def _should_skip(path: Path, ignore_globs: List[str], include_hidden: bool) -> bool:
    # Hidden files/dirs
    if not include_hidden:
        parts = list(path.parts)
        if any(part.startswith(".") for part in parts):
            return True
    # Ignore patterns
    rel = str(path)
    name = path.name
    for pat in ignore_globs:
        if fnmatch(name, pat) or fnmatch(rel, pat):
            return True
    return False


@router.get("/archive", response_class=FileResponse, summary="Download a .tar.gz snapshot")
def make_archive(
    path: str = Query("", description="Directory relative to FS_ROOT to archive"),
    safe_text_only: bool = Query(True, description="Include only safe text files"),
    include_hidden: bool = Query(False, description="Include dotfiles"),
    extra_ignore: Optional[List[str]] = Query(None, description="Additional ignore globs"),
    _: str = Depends(require_api_key),
):
    """
    Builds a .tar.gz under /tmp and returns it. Safe by default:
    - Enforces root confinement and ignore rules
    - Excludes hidden files unless requested
    - When safe_text_only=True (default), only whitelisted text extensions are included
    """
    root = FS_ROOT
    target = _safe_join(root, path or "")
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail="Path not found or not a directory")

    ignore_globs = DEFAULT_IGNORE.copy()
    if extra_ignore:
        ignore_globs.extend(extra_ignore)

    ts = time.strftime("%Y%m%d-%H%M%S")
    # Use folder name or 'root' for nice filename
    base_name = f"export-{(target.name or 'root')}-{ts}"
    out_path = Path(f"/tmp/{base_name}.tar.gz")

    # Create tar.gz (store paths relative to the requested folder)
    with tarfile.open(out_path, mode="w:gz") as tf:
        for p in target.rglob("*"):
            rel = p.relative_to(target)
            full_rel = p.relative_to(root)

            if _should_skip(full_rel, ignore_globs, include_hidden):
                continue
            if p.is_file():
                if safe_text_only and p.suffix.lower() not in SAFE_TEXT_EXTS:
                    continue
                tf.add(p, arcname=str(rel), recursive=False)

    if not out_path.exists() or out_path.stat().st_size == 0:
        raise HTTPException(status_code=500, detail="Archive creation failed")

    return FileResponse(
        path=str(out_path),
        filename=out_path.name,
        media_type="application/gzip",
    )
