from __future__ import annotations

import json
import logging

import pytest

from app.database import SessionLocal
from app.logging_config import JsonFormatter, setup_logging
from app.services.auth_service import bootstrap_token, hash_token, is_auth_required


TOKEN = "test-token-1234567890abcdef"


def _bootstrap(token: str = TOKEN) -> None:
    db = SessionLocal()
    try:
        bootstrap_token(db, token)
    finally:
        db.close()


def test_health_returns_db_ok(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"


def test_ready_returns_scheduler_alive(client):
    response = client.get("/api/v1/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["db"] == "ok"
    assert body["checks"]["scheduler_alive"] is True


def test_auth_status_disabled_by_default(client):
    response = client.get("/api/v1/auth/status")
    assert response.status_code == 200
    assert response.json() == {"auth_required": False}


def test_auth_status_enabled_for_non_loopback_when_token_configured(client):
    _bootstrap()
    response = client.get("/api/v1/auth/status")
    assert response.status_code == 200
    assert response.json()["auth_required"] is True


def test_is_auth_required_false_for_loopback_with_token():
    _bootstrap()
    db = SessionLocal()
    try:
        assert is_auth_required(db, "127.0.0.1") is False
        assert is_auth_required(db, "::1") is False
        assert is_auth_required(db, "localhost") is False
    finally:
        db.close()


def test_is_auth_required_true_for_non_loopback_with_token():
    _bootstrap()
    db = SessionLocal()
    try:
        assert is_auth_required(db, "10.0.0.5") is True
    finally:
        db.close()


def test_is_auth_required_forced_for_loopback(monkeypatch):
    monkeypatch.setenv("LLAMALENS_REQUIRE_AUTH", "1")
    _bootstrap()
    db = SessionLocal()
    try:
        assert is_auth_required(db, "127.0.0.1") is True
    finally:
        db.close()


def test_enforced_when_require_auth_and_no_header(client, monkeypatch):
    monkeypatch.setenv("LLAMALENS_REQUIRE_AUTH", "1")
    _bootstrap()
    assert client.get("/api/v1/settings").status_code == 401


def test_enforced_rejects_wrong_token(client, monkeypatch):
    monkeypatch.setenv("LLAMALENS_REQUIRE_AUTH", "1")
    _bootstrap()
    response = client.get("/api/v1/settings", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


def test_enforced_accepts_correct_token(client, monkeypatch):
    monkeypatch.setenv("LLAMALENS_REQUIRE_AUTH", "1")
    _bootstrap()
    response = client.get("/api/v1/settings", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200


def test_login_success(client):
    _bootstrap()
    response = client.post("/api/v1/auth/login", json={"token": TOKEN})
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_login_wrong_token(client):
    _bootstrap()
    response = client.post("/api/v1/auth/login", json={"token": "wrong"})
    assert response.status_code == 401


def test_login_when_auth_not_configured(client):
    response = client.post("/api/v1/auth/login", json={"token": "anything"})
    assert response.status_code == 401


def test_health_ready_status_exempt_from_auth(client, monkeypatch):
    monkeypatch.setenv("LLAMALENS_REQUIRE_AUTH", "1")
    _bootstrap()
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/ready").status_code == 200
    assert client.get("/api/v1/auth/status").status_code == 200


def test_rotate_updates_token(client, monkeypatch):
    monkeypatch.setenv("LLAMALENS_REQUIRE_AUTH", "1")
    _bootstrap()
    response = client.post(
        "/api/v1/auth/rotate",
        json={"new_token": "new-token-987654321xyz"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200
    assert client.get("/api/v1/settings", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 401
    assert (
        client.get("/api/v1/settings", headers={"Authorization": "Bearer new-token-987654321xyz"}).status_code
        == 200
    )


def test_rotate_requires_existing_token(client, monkeypatch):
    monkeypatch.setenv("LLAMALENS_REQUIRE_AUTH", "1")
    _bootstrap()
    response = client.post("/api/v1/auth/rotate", json={"new_token": "new-token-987654321xyz-long"})
    assert response.status_code == 401


def test_rotate_rejects_short_token(client, monkeypatch):
    monkeypatch.setenv("LLAMALENS_REQUIRE_AUTH", "1")
    _bootstrap()
    response = client.post(
        "/api/v1/auth/rotate",
        json={"new_token": "short"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 422


def test_token_hash_is_stable_and_not_plaintext():
    assert hash_token(TOKEN) == hash_token(TOKEN)
    assert hash_token(TOKEN) != TOKEN
    assert len(hash_token(TOKEN)) == 64


def test_json_formatter_emits_structured_fields():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="systemctl.invoke",
        args=(),
        exc_info=None,
    )
    record.returncode = 0
    output = formatter.format(record)
    payload = json.loads(output)
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"
    assert payload["event"] == "systemctl.invoke"
    assert payload["msg"] == "systemctl.invoke"
    assert payload["returncode"] == 0
    assert "ts" in payload


def test_json_formatter_includes_exception_info():
    formatter = JsonFormatter()
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        import sys

        exc_info = sys.exc_info()
    record = logging.LogRecord(
        name="app.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="uncaught_exception",
        args=(),
        exc_info=exc_info,
    )
    payload = json.loads(formatter.format(record))
    assert payload["level"] == "ERROR"
    assert "RuntimeError" in payload["exc_info"]
    assert "boom" in payload["exc_info"]


def test_setup_logging_is_idempotent():
    setup_logging("INFO")
    setup_logging("DEBUG")
    assert logging.getLogger("app").getEffectiveLevel() in (logging.DEBUG, logging.INFO)
