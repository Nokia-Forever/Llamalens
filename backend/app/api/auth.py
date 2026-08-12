from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.logging_config import get_logger
from app.schemas import LoginInput, RotateTokenInput
from app.services.auth_service import (
    auth_enabled,
    bootstrap_from_env,
    is_auth_required,
    is_loopback,
    require_auth_forced,
    rotate_token,
    verify_token,
)


logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

EXEMPT_PATHS: frozenset[str] = frozenset({
    "/api/v1/health",
    "/api/v1/ready",
    "/api/v1/auth/status",
    "/api/v1/auth/login",
})


def _extract_bearer(header: str) -> str:
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""


def verify_auth(request: Request, db: Session = Depends(get_db)) -> None:
    path = request.url.path
    if path in EXEMPT_PATHS:
        return
    host = request.client.host if request.client else ""
    if is_loopback(host) and not require_auth_forced():
        logger.info("auth.loopback_exempt", extra={"path": path})
        return
    if not auth_enabled(db):
        return
    header = request.headers.get("authorization", "")
    token = _extract_bearer(header)
    if token and verify_token(db, token):
        return
    logger.warning("auth.failed", extra={"path": path, "reason": "missing_or_invalid"})
    raise HTTPException(status_code=401, detail="unauthorized")


@router.get("/status")
def auth_status(request: Request, db: Session = Depends(get_db)) -> dict[str, bool]:
    host = request.client.host if request.client else ""
    return {"auth_required": is_auth_required(db, host)}


@router.post("/login")
def login(payload: LoginInput, db: Session = Depends(get_db)) -> dict[str, bool]:
    if not auth_enabled(db):
        logger.warning("auth.login_failed", extra={"reason": "auth_not_configured"})
        raise HTTPException(status_code=401, detail="unauthorized")
    if not verify_token(db, payload.token):
        logger.warning("auth.login_failed", extra={"reason": "invalid_token"})
        raise HTTPException(status_code=401, detail="unauthorized")
    return {"ok": True}


@router.post("/rotate", dependencies=[Depends(verify_auth)])
def rotate(payload: RotateTokenInput, db: Session = Depends(get_db)) -> dict[str, object]:
    updated = rotate_token(db, payload.new_token)
    logger.info("auth.token_rotated", extra={"updated_at": updated.isoformat()})
    return {"ok": True, "updated_at": updated.isoformat()}


__all__ = ["router", "verify_auth", "EXEMPT_PATHS", "bootstrap_from_env"]
