from __future__ import annotations

import os
import io
import re
import pathlib
import subprocess
from typing import List, Optional, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, validator

# Use your existing auth dependency (API key guard)
from app.deps.auth import require_auth

router = APIRouter(prefix="/ops", tags=["ops"])

WORKSPACE_ROOT = pathlib.Path(".").resolve()

class FileOp(BaseModel):
    op: Literal["write", "delete", "mkdir"]
    path: str
    content: Optional[str] = None  # required when op=write

    @validator("path")
    def no_traversal(cls, v: str) -> str:
        v_norm = v.replace("\\", "/")
        if ".." in v_norm:
            raise ValueError("Path traversal is not allowed")
        if v_norm.startswith("/") or re.match(r"^[A-Za-z]:", v_norm):
            raise ValueError("Absolute paths are not allowed")
        return v

class PatchRequest(BaseModel):
    branch: str = Field(..., description="Branch to commit into (created if missing)")
    message: str = Field(..., description="Commit message")
    ops: List[FileOp]
    base_ref: str = Field("main", description="Base branch if creating new")
    create_branch_if_missing: bool = True
    auto_add: bool = True

def _run(cmd: List[str]) -> str:
    p = subprocess.run(cmd, cwd=str(WORKSPACE_ROOT), capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\nstdout:\n{p.stdout}\nstderr:\n{p.stderr}"
        )
    return p.stdout.strip()

def _ensure_branch(branch: str, base_ref: str, create: bool) -> None:
    # Fetch base and ensure working on correct branch
    try:
        _run(["git", "fetch", "origin", base_ref])
    except Exception:
        # repo might already have base locally; proceed
        pass

    current = _run(["git", "branch", "--list", branch])
    if not current:
        if create:
            # create new branch from origin/base_ref (or base_ref if local)
            try:
                _run(["git", "checkout", "-B", branch, f"origin/{base_ref}"])
            except Exception:
                _run(["git", "checkout", "-B", branch, base_ref])
        else:
            raise RuntimeError(f"Branch {branch} does not exist and creation is disabled")
    else:
        _run(["git", "checkout", branch])
        # Rebase on latest base to keep branch up to date
        try:
            _run(["git", "rebase", f"origin/{base_ref}"])
        except Exception:
            # if origin/<base> not present, rebase on local base
            _run(["git", "rebase", base_ref])

@router.post("/patch", dependencies=[Depends(require_auth)])
def apply_patch(req: PatchRequest):
    """
    Apply file ops in the Codespace working tree, commit, push, and (if gh is available) open a PR.
    """
    try:
        _ensure_branch(req.branch, req.base_ref, req.create_branch_if_missing)

        for op in req.ops:
            target = (WORKSPACE_ROOT / op.path).resolve()

            # Keep within workspace
            if not str(target).startswith(str(WORKSPACE_ROOT)):
                raise HTTPException(status_code=400, detail="Invalid path outside workspace")

            if op.op == "mkdir":
                target.mkdir(parents=True, exist_ok=True)

            elif op.op == "write":
                if op.content is None:
                    raise HTTPException(status_code=400, detail=f"content required for write: {op.path}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with io.open(target, "w", encoding="utf-8", newline="") as f:
                    f.write(op.content)

            elif op.op == "delete":
                if target.is_file():
                    target.unlink()
                elif target.is_dir():
                    if target == WORKSPACE_ROOT:
                        raise HTTPException(status_code=400, detail="Refusing to delete repository root")
                    for root, dirs, files in os.walk(target, topdown=False):
                        for name in files:
                            pathlib.Path(root, name).unlink()
                        for name in dirs:
                            pathlib.Path(root, name).rmdir()
                    target.rmdir()
                else:
                    # missing is fine
                    pass

            else:
                raise HTTPException(status_code=400, detail=f"Unknown op: {op.op}")

        if req.auto_add:
            _run(["git", "add", "--all"])

        status = _run(["git", "status", "--porcelain"])
        if not status:
            return {"ok": True, "message": "No changes to commit", "branch": req.branch}

        _run(["git", "commit", "-m", req.message])
        _run(["git", "push", "origin", req.branch])

        pr_url = None
        try:
            pr_url = _run([
                "gh", "pr", "create",
                "--head", req.branch,
                "--base", req.base_ref,
                "--title", req.message,
                "--body", "Automated patch from /ops/patch"
            ])
        except Exception:
            # gh not installed or auth not set; that's fine
            pass

        return {"ok": True, "branch": req.branch, "pr": pr_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
