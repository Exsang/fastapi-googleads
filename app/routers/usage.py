from fastapi import APIRouter, Depends
from ..deps.auth import require_auth
from ..services.usage_log import read_usage_log, usage_summary

router = APIRouter(prefix="/ads", tags=["usage"], dependencies=[Depends(require_auth)])

@router.get("/usage-log")
def get_usage_log(limit: int = 100, offset: int = 0):
    return read_usage_log(limit, offset)

@router.get("/usage-summary")
def get_usage_summary():
    return usage_summary()
