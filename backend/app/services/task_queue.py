from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import BenchmarkJob, BenchmarkTask, TaskQueue, TaskQueueItem, TaskQueueHistory
from app.services.benchmark import cancel_benchmark, create_run_for_task, is_benchmark_active, run_benchmark_job


def _aware_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

_scheduler: QueueScheduler | None = None


def get_scheduler() -> QueueScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = QueueScheduler()
    return _scheduler


def _ensure_queue_row(db: Session) -> TaskQueue:
    q = db.get(TaskQueue, 1)
    if q is None:
        q = TaskQueue(id=1, status="idle", interval_ms=0, cancel_timeout_ms=60000)
        db.add(q)
        db.commit()
        db.flush()
    return q


def _record_history(
    db: Session,
    item_id: str | None,
    task_id: str,
    action: str,
    run_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    db.add(TaskQueueHistory(
        item_id=item_id,
        task_id=task_id,
        action=action,
        run_id=run_id,
        detail_json=json.dumps(detail or {}, ensure_ascii=False),
        at=datetime.now(timezone.utc),
    ))


def _update_task_stats(db: Session, task_id: str, run_status: str) -> None:
    task = db.get(BenchmarkTask, task_id)
    if task is None:
        return
    task.last_run_status = run_status
    task.run_count = (task.run_count or 0) + 1


def _serialize_item(db: Session, item: TaskQueueItem) -> dict[str, Any]:
    task = db.get(BenchmarkTask, item.task_id)
    result: dict[str, Any] = {
        "id": item.id,
        "task_id": item.task_id,
        "task_name": task.name if task else "(已删除)",
        "order_index": item.order_index,
        "status": item.status,
        "enqueued_at": item.enqueued_at,
        "started_at": item.started_at,
        "last_run_id": item.last_run_id,
    }
    if item.last_run_id:
        job = db.get(BenchmarkJob, item.last_run_id)
        if job:
            result["run"] = {
                "id": job.id,
                "status": job.status,
                "name": job.name,
                "error": job.error,
                "summary": json.loads(job.summary_json) if job.summary_json else {},
            }
    return result


def serialize_queue(db: Session, q: TaskQueue) -> dict[str, Any]:
    items = db.scalars(
        select(TaskQueueItem).order_by(TaskQueueItem.order_index.asc())
    ).all()

    current_item: dict[str, Any] | None = None
    if q.current_item_id:
        item = db.get(TaskQueueItem, q.current_item_id)
        if item:
            current_item = _serialize_item(db, item)

    session_stats: dict[str, int] = {"successes": 0, "failures": 0, "canceled": 0}
    if q.session_id:
        session_jobs = db.scalars(
            select(BenchmarkJob).where(BenchmarkJob.queue_session_id == q.session_id)
        ).all()
        for job in session_jobs:
            if job.status == "succeeded":
                session_stats["successes"] += 1
            elif job.status == "failed":
                session_stats["failures"] += 1
            elif job.status == "cancelled":
                session_stats["canceled"] += 1

    return {
        "id": q.id,
        "status": q.status,
        "interval_ms": q.interval_ms,
        "cancel_timeout_ms": q.cancel_timeout_ms,
        "current_item_id": q.current_item_id,
        "next_dispatch_at": q.next_dispatch_at,
        "session_id": q.session_id,
        "items": [_serialize_item(db, item) for item in items],
        "current_item": current_item,
        "session_stats": session_stats,
    }


def get_queue_state(db: Session) -> dict[str, Any]:
    q = _ensure_queue_row(db)
    return serialize_queue(db, q)


def start_queue(db: Session) -> dict[str, Any]:
    q = _ensure_queue_row(db)
    if q.status in ("running", "stopping"):
        raise ValueError(f"队列当前状态为 {q.status}，无法开始")
    if is_benchmark_active():
        raise ValueError("有一个 Benchmark 正在运行，请等待完成后再开始队列")
    q.status = "running"
    q.session_id = str(uuid.uuid4())
    q.next_dispatch_at = None
    db.commit()
    get_scheduler().notify()
    return serialize_queue(db, q)


def pause_queue(db: Session) -> dict[str, Any]:
    q = _ensure_queue_row(db)
    if q.status not in ("running",):
        raise ValueError(f"队列当前状态为 {q.status}，无法暂停")
    q.status = "paused"
    db.commit()
    get_scheduler().notify()
    return serialize_queue(db, q)


def update_queue_settings(
    db: Session,
    interval_ms: int | None = None,
    cancel_timeout_ms: int | None = None,
) -> dict[str, Any]:
    q = _ensure_queue_row(db)
    if interval_ms is not None:
        q.interval_ms = interval_ms
    if cancel_timeout_ms is not None:
        q.cancel_timeout_ms = cancel_timeout_ms
    db.commit()
    get_scheduler().notify()
    return serialize_queue(db, q)


def enqueue_item(db: Session, task_id: str, position: str | int = "tail") -> dict[str, Any]:
    _ensure_queue_row(db)
    task = db.get(BenchmarkTask, task_id)
    if task is None:
        raise ValueError("任务不存在")

    if position == "head":
        waiting_items = db.scalars(
            select(TaskQueueItem)
            .where(TaskQueueItem.status == "waiting")
            .order_by(TaskQueueItem.order_index.desc())
        ).all()
        for existing in waiting_items:
            existing.order_index += 1
        order_index = 1
    elif isinstance(position, int) and position > 0:
        to_shift = db.scalars(
            select(TaskQueueItem)
            .where(TaskQueueItem.status == "waiting", TaskQueueItem.order_index >= position)
            .order_by(TaskQueueItem.order_index.desc())
        ).all()
        for existing in to_shift:
            existing.order_index += 1
        order_index = position
    else:
        max_order = db.scalar(select(func.max(TaskQueueItem.order_index))) or 0
        order_index = max_order + 1

    item = TaskQueueItem(
        id=str(uuid.uuid4()),
        task_id=task_id,
        order_index=order_index,
        status="waiting",
        enqueued_at=datetime.now(timezone.utc),
    )
    db.add(item)
    db.flush()
    _record_history(db, item.id, task_id, "enqueued", detail={"order_index": order_index})
    db.commit()
    db.refresh(item)
    get_scheduler().notify()
    return _serialize_item(db, item)


def reorder_items(db: Session, item_ids: list[str]) -> None:
    _ensure_queue_row(db)
    items_map: dict[str, TaskQueueItem] = {}
    for item_id in item_ids:
        item = db.get(TaskQueueItem, item_id)
        if item is None:
            raise ValueError(f"队列项 {item_id} 不存在")
        if item.status != "waiting":
            raise ValueError(f"正在执行的队列项不能调整顺序")
        items_map[item_id] = item
    for index, item_id in enumerate(item_ids, start=1):
        items_map[item_id].order_index = index
    _record_history(db, None, "", "reordered", detail={"item_ids": item_ids})
    db.commit()
    get_scheduler().notify()


def delete_item(db: Session, item_id: str) -> dict[str, Any]:
    q = _ensure_queue_row(db)
    item = db.get(TaskQueueItem, item_id)
    if item is None:
        raise ValueError("队列项不存在")

    if item.id == q.current_item_id:
        if q.status != "stopping":
            q.status = "stopping"
        if item.last_run_id:
            cancel_benchmark(item.last_run_id)
        _record_history(db, item.id, item.task_id, "canceled", item.last_run_id, {"reason": "stop-and-delete"})
        db.commit()
        get_scheduler().notify()
        return {"ok": True, "stopping": True}
    else:
        _record_history(db, item.id, item.task_id, "removed", detail={"reason": "user-delete"})
        db.delete(item)
        db.commit()
        get_scheduler().notify()
        return {"ok": True, "stopping": False}


def recover_on_startup() -> None:
    db = SessionLocal()
    try:
        q = _ensure_queue_row(db)
        if q.current_item_id is not None:
            item = db.get(TaskQueueItem, q.current_item_id)
            if item and item.last_run_id:
                job = db.get(BenchmarkJob, item.last_run_id)
                if job and job.status in ("queued", "running"):
                    job.status = "failed"
                    job.error = "interrupted by restart"
                    job.finished_at = datetime.now(timezone.utc)
                    _update_task_stats(db, item.task_id, "failed")
            if item:
                _record_history(db, item.id, item.task_id, "canceled", item.last_run_id, {"reason": "restart"})
                db.delete(item)
            q.current_item_id = None
        q.status = "idle"
        now = datetime.now(timezone.utc)
        next_at = _aware_utc(q.next_dispatch_at)
        if next_at is not None and next_at <= now:
            q.next_dispatch_at = None
        db.commit()
    finally:
        db.close()


class QueueScheduler:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._thread = threading.Thread(target=self._loop, name="llamalens-queue-scheduler", daemon=True)
        self._running = False

    def start(self) -> None:
        self._running = True
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self.notify()

    def notify(self) -> None:
        with self._condition:
            self._condition.notify_all()

    def _loop(self) -> None:
        while self._running:
            try:
                self._tick()
            except Exception:
                pass
            with self._condition:
                self._condition.wait(timeout=1.0)

    def _tick(self) -> None:
        job_id: str | None = None
        db = SessionLocal()
        try:
            q = _ensure_queue_row(db)
            if q.status not in ("running", "stopping"):
                return

            if q.current_item_id is None and q.status == "running":
                self._try_dispatch(db, q)

            if q.current_item_id is not None:
                item = db.get(TaskQueueItem, q.current_item_id)
                job_id = item.last_run_id if item else None
        finally:
            db.close()

        if job_id:
            run_benchmark_job(job_id)

            db = SessionLocal()
            try:
                q = db.get(TaskQueue, 1)
                if q and q.current_item_id is not None:
                    self._handle_run_finished(db, q)
            finally:
                db.close()
            self.notify()

    def _try_dispatch(self, db: Session, q: TaskQueue) -> None:
        now = datetime.now(timezone.utc)

        next_at = _aware_utc(q.next_dispatch_at)
        if next_at is not None and now < next_at:
            return

        waiting = db.scalars(
            select(TaskQueueItem)
            .where(TaskQueueItem.status == "waiting")
            .order_by(TaskQueueItem.order_index.asc())
        ).all()

        if not waiting:
            q.status = "idle"
            q.next_dispatch_at = None
            db.commit()
            return

        item = waiting[0]
        task = db.get(BenchmarkTask, item.task_id)
        if task is None:
            db.delete(item)
            db.commit()
            return

        try:
            job = create_run_for_task(db, task, q.session_id)
        except Exception as exc:
            job = BenchmarkJob(
                id=str(uuid.uuid4()),
                name=task.name,
                service_id=task.service_id,
                model_alias=task.model_alias,
                task_id=task.id,
                queue_session_id=q.session_id,
                status="failed",
                config_json="{}",
                summary_json="{}",
                error=str(exc),
                finished_at=datetime.now(timezone.utc),
            )
            db.add(job)
            db.flush()
            _record_history(db, item.id, item.task_id, "finished", job.id, {"status": "failed", "error": str(exc)})
            _update_task_stats(db, task.id, "failed")
            db.delete(item)
            q.next_dispatch_at = now + timedelta(milliseconds=q.interval_ms)
            db.commit()
            self.notify()
            return

        item.status = "running"
        item.started_at = now
        item.last_run_id = job.id
        q.current_item_id = item.id
        db.commit()
        _record_history(db, item.id, item.task_id, "started", job.id, {})

    def _handle_run_finished(self, db: Session, q: TaskQueue) -> None:
        item_id = q.current_item_id
        if item_id is None:
            return

        item = db.get(TaskQueueItem, item_id)
        if item is None:
            q.current_item_id = None
            db.commit()
            return

        job = db.get(BenchmarkJob, item.last_run_id) if item.last_run_id else None
        now = datetime.now(timezone.utc)
        run_status = job.status if job else "failed"
        action = "canceled" if run_status == "cancelled" else "finished"

        _record_history(db, item.id, item.task_id, action, item.last_run_id,
                        {"status": run_status, "error": job.error if job else None})
        _update_task_stats(db, item.task_id, run_status)

        db.delete(item)
        q.current_item_id = None

        waiting_count = db.scalar(
            select(func.count()).select_from(TaskQueueItem).where(TaskQueueItem.status == "waiting")
        ) or 0

        if q.status == "stopping":
            q.status = "running" if waiting_count > 0 else "idle"
            q.next_dispatch_at = None if waiting_count == 0 else q.next_dispatch_at
        else:
            if waiting_count > 0:
                q.next_dispatch_at = now + timedelta(milliseconds=q.interval_ms) if q.interval_ms > 0 else None
            else:
                q.status = "idle"
                q.next_dispatch_at = None

        db.commit()
