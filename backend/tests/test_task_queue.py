from __future__ import annotations

import threading
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    BenchmarkJob,
    BenchmarkTask,
    DownloadJob,
    LlamaService,
    TaskQueue,
    TaskQueueItem,
)
from app.services import task_queue
from app.services.benchmark import _cancelled_jobs


def _seed_service_and_task(db: Session, task_id: str = "task-1", service_id: str = "svc-1") -> None:
    db.add(LlamaService(
        id=service_id, name=service_id, unit_name=f"{service_id}.service",
        unit_path="/etc/systemd/system/svc.service", server_bin="/opt/llama-server",
    ))
    db.add(BenchmarkTask(id=task_id, name=task_id, service_id=service_id, config_json='{"prompt":"hi"}'))
    db.commit()


@pytest.fixture(autouse=True)
def _isolate_scheduler():
    task_queue._scheduler = None
    yield
    sched = task_queue._scheduler
    if sched is not None:
        sched.stop()
        if sched._thread is not None and sched._thread.is_alive():
            sched._thread.join(timeout=2.0)
    task_queue._scheduler = None


def test_recover_on_startup_fails_orphans_and_removes_part_file(tmp_path):
    part_file = tmp_path / "model.gguf.part"
    part_file.write_bytes(b"partial-bytes")
    target_path = str(tmp_path / "model.gguf")

    db = SessionLocal()
    try:
        _seed_service_and_task(db)
        db.add(BenchmarkJob(id="bj-standalone", name="standalone", status="running", config_json="{}", summary_json="{}"))
        db.add(BenchmarkJob(id="bj-current", name="current", status="running", config_json="{}", summary_json="{}"))
        db.add(DownloadJob(id="dl-1", url="http://example/model.gguf", target_path=target_path, status="running"))
        db.add(TaskQueueItem(id="item-1", task_id="task-1", order_index=1, status="running", last_run_id="bj-current"))
        db.add(TaskQueue(id=1, status="running", current_item_id="item-1"))
        db.commit()
    finally:
        db.close()

    task_queue.recover_on_startup()

    assert part_file.exists() is False
    db = SessionLocal()
    try:
        assert db.get(BenchmarkJob, "bj-standalone").status == "failed"
        assert db.get(BenchmarkJob, "bj-current").status == "failed"
        assert db.get(DownloadJob, "dl-1").status == "failed"
        assert db.get(TaskQueueItem, "item-1") is None
        q = db.get(TaskQueue, 1)
        assert q.current_item_id is None
        assert q.status == "idle"
    finally:
        db.close()


def test_scheduler_persists_error_state_at_threshold(monkeypatch):
    monkeypatch.setenv("LLAMALENS_QUEUE_FAILURE_THRESHOLD", "2")
    monkeypatch.setenv("LLAMALENS_QUEUE_ERROR_COOLDOWN_MS", "100")

    sched = task_queue.get_scheduler()
    db = SessionLocal()
    try:
        q = task_queue._ensure_queue_row(db)
        q.status = "running"
        db.commit()
    finally:
        db.close()

    sched._handle_tick_failure(RuntimeError("boom-1"))
    assert sched.diagnostics()["consecutive_failures"] == 1
    db = SessionLocal()
    try:
        assert db.get(TaskQueue, 1).status == "running"
    finally:
        db.close()

    sched._handle_tick_failure(RuntimeError("boom-2"))
    diag = sched.diagnostics()
    assert diag["consecutive_failures"] == 2
    assert diag["last_error"] == "RuntimeError: boom-2"
    assert diag["last_error_at"] is not None
    db = SessionLocal()
    try:
        assert db.get(TaskQueue, 1).status == "error"
    finally:
        db.close()


def test_scheduler_auto_recovers_from_error_state(monkeypatch):
    monkeypatch.setenv("LLAMALENS_QUEUE_FAILURE_THRESHOLD", "2")
    monkeypatch.setenv("LLAMALENS_QUEUE_ERROR_COOLDOWN_MS", "100")

    sched = task_queue.get_scheduler()
    db = SessionLocal()
    try:
        q = task_queue._ensure_queue_row(db)
        q.status = "running"
        db.commit()
    finally:
        db.close()

    sched._handle_tick_failure(RuntimeError("boom"))
    sched._handle_tick_failure(RuntimeError("boom"))
    db = SessionLocal()
    try:
        assert db.get(TaskQueue, 1).status == "error"
    finally:
        db.close()

    sched._attempt_error_recovery()
    sched._on_tick_success()

    db = SessionLocal()
    try:
        assert db.get(TaskQueue, 1).status == "running"
    finally:
        db.close()
    diag = sched.diagnostics()
    assert diag["consecutive_failures"] == 0
    assert diag["last_error"] is None


def test_ready_reports_degraded_for_error_queue(client):
    db = SessionLocal()
    try:
        q = task_queue._ensure_queue_row(db)
        q.status = "error"
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/v1/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["checks"]["queue_status"] == "error"
    assert body["checks"]["db"] == "ok"


def test_ready_reports_degraded_for_scheduler_failures(client):
    sched = task_queue.get_scheduler()
    sched._consecutive_failures = 1
    sched._last_error = "RuntimeError: injected"
    sched._last_error_at = datetime.now(timezone.utc)
    try:
        resp = client.get("/api/v1/ready")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["checks"]["scheduler_failures"] == 1
    finally:
        sched.reset_diagnostics()


def test_queue_state_exposes_scheduler_diagnostics(client):
    resp = client.get("/api/v1/queue")
    assert resp.status_code == 200
    body = resp.json()
    assert "scheduler" in body
    assert body["scheduler"]["failure_threshold"] >= 1
    assert body["scheduler"]["consecutive_failures"] == 0


def test_reset_queue_via_http_clears_error_then_conflicts(client):
    db = SessionLocal()
    try:
        q = task_queue._ensure_queue_row(db)
        q.status = "error"
        db.commit()
    finally:
        db.close()

    resp = client.post("/api/v1/queue/reset")
    assert resp.status_code == 200
    assert resp.json()["status"] == "idle"

    resp2 = client.post("/api/v1/queue/reset")
    assert resp2.status_code == 409


def test_stop_queue_returns_current_item_to_waiting():
    _cancelled_jobs.discard("bj-stop")
    db = SessionLocal()
    try:
        _seed_service_and_task(db)
        db.add(BenchmarkJob(id="bj-stop", name="stop", status="running", config_json="{}", summary_json="{}"))
        db.add(TaskQueueItem(id="item-1", task_id="task-1", order_index=1, status="running", last_run_id="bj-stop"))
        db.add(TaskQueue(id=1, status="running", current_item_id="item-1", session_id="sess-1"))
        db.commit()
    finally:
        db.close()

    sched = task_queue.get_scheduler()
    db = SessionLocal()
    try:
        result = task_queue.stop_queue(db)
        assert result["status"] == "stopping_queue"
        q = db.get(TaskQueue, 1)
        assert q.status == "stopping_queue"

        db.get(BenchmarkJob, "bj-stop").status = "cancelled"
        db.commit()
        sched._handle_run_finished(db, q)

        db.refresh(q)
        assert q.status == "idle"
        assert q.current_item_id is None
        item = db.get(TaskQueueItem, "item-1")
        assert item is not None
        assert item.status == "waiting"
        assert item.last_run_id is None
        assert item.started_at is None
    finally:
        db.close()
        _cancelled_jobs.discard("bj-stop")


def test_delete_current_item_stops_then_removes():
    _cancelled_jobs.discard("bj-del")
    db = SessionLocal()
    try:
        _seed_service_and_task(db)
        db.add(BenchmarkJob(id="bj-del", name="del", status="running", config_json="{}", summary_json="{}"))
        db.add(TaskQueueItem(id="item-1", task_id="task-1", order_index=1, status="running", last_run_id="bj-del"))
        db.add(TaskQueue(id=1, status="running", current_item_id="item-1", session_id="sess-1"))
        db.commit()
    finally:
        db.close()

    sched = task_queue.get_scheduler()
    db = SessionLocal()
    try:
        result = task_queue.delete_item(db, "item-1")
        assert result == {"ok": True, "stopping": True}
        q = db.get(TaskQueue, 1)
        assert q.status == "stopping"

        db.get(BenchmarkJob, "bj-del").status = "cancelled"
        db.commit()
        sched._handle_run_finished(db, q)

        db.refresh(q)
        assert q.current_item_id is None
        assert q.status == "idle"
        assert db.get(TaskQueueItem, "item-1") is None
    finally:
        db.close()
        _cancelled_jobs.discard("bj-del")


def test_concurrent_enqueue_under_lock_is_safe():
    db = SessionLocal()
    try:
        _seed_service_and_task(db)
    finally:
        db.close()

    n = 8
    barrier = threading.Barrier(n)
    errors: list[BaseException] = []

    def worker():
        try:
            ldb = SessionLocal()
            try:
                barrier.wait(timeout=5)
                task_queue.enqueue_item(ldb, "task-1", "tail")
            finally:
                ldb.close()
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert errors == [], errors
    db = SessionLocal()
    try:
        items = db.scalars(select(TaskQueueItem).order_by(TaskQueueItem.order_index)).all()
        assert len(items) == n
        indexes = [i.order_index for i in items]
        assert len(set(indexes)) == n
    finally:
        db.close()


def test_serialize_queue_query_count_is_constant():
    from sqlalchemy import event
    from app.database import Base, engine

    def run(n_items):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        try:
            _seed_service_and_task(db)
            for i in range(n_items):
                db.add(TaskQueueItem(id=f"item-{i}", task_id="task-1", order_index=i, status="waiting"))
            db.add(TaskQueue(id=1, status="idle"))
            db.commit()
        finally:
            db.close()
        counts = {"n": 0}

        def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            counts["n"] += 1

        event.listen(engine, "before_cursor_execute", before_cursor_execute)
        try:
            db = SessionLocal()
            try:
                q = db.get(TaskQueue, 1)
                task_queue.serialize_queue(db, q)
            finally:
                db.close()
        finally:
            event.remove(engine, "before_cursor_execute", before_cursor_execute)
        return counts["n"]

    small = run(3)
    large = run(8)
    assert small == large, f"query count grew with items: {small} -> {large}"


def test_session_stats_aggregate(client):
    db = SessionLocal()
    try:
        _seed_service_and_task(db)
        session_id = "test-session-1"
        db.add(BenchmarkJob(id="bj-succ", name="s", status="succeeded", config_json="{}", summary_json="{}", queue_session_id=session_id))
        db.add(BenchmarkJob(id="bj-succ2", name="s2", status="succeeded", config_json="{}", summary_json="{}", queue_session_id=session_id))
        db.add(BenchmarkJob(id="bj-fail", name="f", status="failed", config_json="{}", summary_json="{}", queue_session_id=session_id))
        db.add(BenchmarkJob(id="bj-cancel", name="c", status="cancelled", config_json="{}", summary_json="{}", queue_session_id=session_id))
        db.add(BenchmarkJob(id="bj-other", name="o", status="succeeded", config_json="{}", summary_json="{}", queue_session_id="other-session"))
        q = task_queue._ensure_queue_row(db)
        q.status = "running"
        q.session_id = session_id
        db.commit()
    finally:
        db.close()
    body = client.get("/api/v1/queue").json()
    assert body["session_stats"] == {"successes": 2, "failures": 1, "canceled": 1}


def test_scheduler_publish_reaches_subscriber(monkeypatch):
    monkeypatch.setenv("LLAMALENS_SSE_QUEUE_MAXSIZE", "2")
    sched = task_queue.get_scheduler()
    subscriber = sched.subscribe()
    try:
        sched.notify()
        assert subscriber.get(timeout=0.5) is None
    finally:
        sched.unsubscribe(subscriber)
    assert subscriber not in sched._subscribers
