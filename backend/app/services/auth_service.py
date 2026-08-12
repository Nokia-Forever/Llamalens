from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import AuthSecret


_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_loopback(host: str | None) -> bool:
    return (host or "") in _LOOPBACK_HOSTS


def require_auth_forced() -> bool:
    return os.getenv("LLAMALENS_REQUIRE_AUTH", "0") == "1"


def get_auth_secret(db: Session) -> AuthSecret | None:
    return db.get(AuthSecret, 1)


def auth_enabled(db: Session) -> bool:
    secret = get_auth_secret(db)
    return bool(secret and secret.token_hash)


def is_auth_required(db: Session, host: str | None) -> bool:
    if is_loopback(host) and not require_auth_forced():
        return False
    return auth_enabled(db)


def verify_token(db: Session, token: str) -> bool:
    secret = get_auth_secret(db)
    if not secret or not secret.token_hash or not token:
        return False
    return secrets.compare_digest(secret.token_hash, hash_token(token))


def bootstrap_token(db: Session, token: str) -> datetime:
    now = datetime.now(timezone.utc)
    secret = get_auth_secret(db)
    token_hash = hash_token(token)
    if secret is None:
        secret = AuthSecret(id=1, token_hash=token_hash, updated_at=now)
        db.add(secret)
    else:
        secret.token_hash = token_hash
        secret.updated_at = now
    db.commit()
    return now


def rotate_token(db: Session, new_token: str) -> datetime:
    now = datetime.now(timezone.utc)
    secret = get_auth_secret(db)
    token_hash = hash_token(new_token)
    if secret is None:
        secret = AuthSecret(id=1, token_hash=token_hash, updated_at=now)
        db.add(secret)
    else:
        secret.token_hash = token_hash
        secret.updated_at = now
    db.commit()
    return now


def bootstrap_from_env(db: Session) -> bool:
    token_env = os.getenv("LLAMALENS_API_TOKEN", "").strip()
    if not token_env:
        return False
    bootstrap_token(db, token_env)
    return True
