from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import DownloadJob
from app.services import models_service


class _FakeResponse:
    def raise_for_status(self):
        return None

    headers = {"content-length": "61440"}

    def iter_bytes(self, _size):
        for _ in range(60):
            yield b"x" * 1024


class _FakeStream:
    def __enter__(self):
        return _FakeResponse()

    def __exit__(self, *_args):
        return None


def test_download_throttles_db_commits(monkeypatch, tmp_path):
    monkeypatch.setattr(models_service.httpx, "stream", lambda *a, **k: _FakeStream())
    monkeypatch.setenv("LLAMALENS_DOWNLOAD_COMMIT_INTERVAL_BYTES", str(16 * 1024 * 1024))
    monkeypatch.setenv("LLAMALENS_DOWNLOAD_COMMIT_INTERVAL_MS", "2000")
    models_service._cancelled_downloads.discard("dl-throttle")

    db = SessionLocal()
    try:
        target = str(tmp_path / "model.gguf")
        db.add(DownloadJob(id="dl-throttle", url="http://example/model.gguf", target_path=target, status="queued"))
        db.commit()
    finally:
        db.close()

    commit_count = {"n": 0}

    def after_commit(_session):
        commit_count["n"] += 1

    event.listen(Session, "after_commit", after_commit)
    try:
        models_service._run_download("dl-throttle", 30)
    finally:
        event.remove(Session, "after_commit", after_commit)

    assert commit_count["n"] < 60
    assert commit_count["n"] <= 6
    db = SessionLocal()
    try:
        job = db.get(DownloadJob, "dl-throttle")
        assert job.status == "succeeded"
        assert job.downloaded_bytes == 60 * 1024
    finally:
        db.close()
