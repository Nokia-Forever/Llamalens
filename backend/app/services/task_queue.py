from __future__ import annotations

import json
import os
import queue
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.logging_config import get_logger
from app.models import BenchmarkJob, BenchmarkTask, DownloadJob, TaskQueue, TaskQueueItem, TaskQueueHistory
from app.services.benchmark import cancel_benchmark, create_run_for_task, is_benchmark_active, run_benchmark_job


logger = get_logger(__name__)


def _aware_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _failure_threshold() -> int:
    try:
        return max(1, int(os.getenv("LLAMALENS_QUEUE_FAILURE_THRESHOLD", "5")))
    except ValueError:
        return 5


def _error_cooldown_seconds() -> float:
    try:
        return max(1.0, int(os.getenv("LLAMALENS_QUEUE_ERROR_COOLDOWN_MS", "30000")) / 1000.0)
    except ValueError:
        return 30.0


def _sse_queue_maxsize() -> int:
    try:
        return max(1, int(os.getenv("LLAMALENS_SSE_QUEUE_MAXSIZE", "16")))
    except ValueError:
        return 16


def _format_error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


_queue_lock = threading.Lock()

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


def _serialize_item(
    item: TaskQueueItem,
    task: BenchmarkTask | None = None,
    job: BenchmarkJob | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": item.id,
        "task_id": item.task_id,
        "task_name": task.name if task else "(已删除)",
        "run_name": item.run_name,
        "order_index": item.order_index,
        "status": item.status,
        "enqueued_at": item.enqueued_at,
        "started_at": item.started_at,
        "last_run_id": item.last_run_id,
    }
    if item.last_run_id and job:
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

    task_ids = {item.task_id for item in items}
    run_ids = {item.last_run_id for item in items if item.last_run_id}

    tasks_map: dict[str, BenchmarkTask] = {}
    if task_ids:
        for t in db.scalars(select(BenchmarkTask).where(BenchmarkTask.id.in_(task_ids))).all():
            tasks_map[t.id] = t

    jobs_map: dict[str, BenchmarkJob] = {}
    if run_ids:
        for j in db.scalars(select(BenchmarkJob).where(BenchmarkJob.id.in_(run_ids))).all():
            jobs_map[j.id] = j

    current_item: dict[str, Any] | None = None
    if q.current_item_id:
        current = next((it for it in items if it.id == q.current_item_id), None)
        if current:
            cur_task = tasks_map.get(current.task_id)
            cur_job = jobs_map.get(current.last_run_id) if current.last_run_id else None
            current_item = _serialize_item(current, cur_task, cur_job)

    session_stats: dict[str, int] = {"successes": 0, "failures": 0, "canceled": 0}
    if q.session_id:
        rows = db.execute(
            select(BenchmarkJob.status, func.count())
            .where(BenchmarkJob.queue_session_id == q.session_id)
            .group_by(BenchmarkJob.status)
        ).all()
        for status, count in rows:
            if status == "succeeded":
                session_stats["successes"] = count
            elif status == "failed":
                session_stats["failures"] = count
            elif status == "cancelled":
                session_stats["canceled"] = count

    return {
        "id": q.id,
        "status": q.status,
        "interval_ms": q.interval_ms,
        "cancel_timeout_ms": q.cancel_timeout_ms,
        "current_item_id": q.current_item_id,
        "next_dispatch_at": q.next_dispatch_at,
        "session_id": q.session_id,
        "items": [
            _serialize_item(
                item,
                tasks_map.get(item.task_id),
                jobs_map.get(item.last_run_id) if item.last_run_id else None,
            )
            for item in items
        ],
        "current_item": current_item,
        "session_stats": session_stats,
        "scheduler": get_scheduler().diagnostics(),
    }


def get_queue_state(db: Session) -> dict[str, Any]:
    q = _ensure_queue_row(db)
    return serialize_queue(db, q)


def get_queue_diagnostics(db: Session) -> dict[str, Any]:
    q = db.get(TaskQueue, 1)
    return {
        "queue_status": q.status if q else "idle",
        "scheduler": get_scheduler().diagnostics(),
    }


def start_queue(db: Session) -> dict[str, Any]:
    with _queue_lock:
        q = _ensure_queue_row(db)
        if q.status in ("running", "stopping", "stopping_queue"):
            raise ValueError(f"队列当前状态为 {q.status}，无法开始")
        if is_benchmark_active():
            raise ValueError("有一个 Benchmark 正在运行，请等待完成后再开始队列")
        q.status = "running"
        q.session_id = str(uuid.uuid4())
        q.next_dispatch_at = None
        db.commit()
        result = serialize_queue(db, q)
    get_scheduler().notify()
    return result


def pause_queue(db: Session) -> dict[str, Any]:
    with _queue_lock:
        q = _ensure_queue_row(db)
        if q.status not in ("running",):
            raise ValueError(f"队列当前状态为 {q.status}，无法暂停")
        q.status = "paused"
        db.commit()
        result = serialize_queue(db, q)
    get_scheduler().notify()
    return result


def update_queue_settings(
    db: Session,
    interval_ms: int | None = None,
    cancel_timeout_ms: int | None = None,
) -> dict[str, Any]:
    with _queue_lock:
        q = _ensure_queue_row(db)
        if interval_ms is not None:
            q.interval_ms = interval_ms
        if cancel_timeout_ms is not None:
            q.cancel_timeout_ms = cancel_timeout_ms
        db.commit()
        result = serialize_queue(db, q)
    get_scheduler().notify()
    return result


def enqueue_item(db: Session, task_id: str, position: str | int = "tail", run_name: str | None = None) -> dict[str, Any]:
    with _queue_lock:
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
            run_name=(run_name.strip() if run_name and run_name.strip() else None),
            enqueued_at=datetime.now(timezone.utc),
        )
        db.add(item)
        db.flush()
        _record_history(db, item.id, task_id, "enqueued", detail={"order_index": order_index, "run_name": item.run_name})
        db.commit()
        db.refresh(item)
        task = db.get(BenchmarkTask, item.task_id)
        job = db.get(BenchmarkJob, item.last_run_id) if item.last_run_id else None
        result = _serialize_item(item, task, job)
    get_scheduler().notify()
    return result


def reorder_items(db: Session, item_ids: list[str]) -> None:
    with _queue_lock:
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
    last_run_id: str | None = None
    stopping = False
    with _queue_lock:
        q = _ensure_queue_row(db)
        item = db.get(TaskQueueItem, item_id)
        if item is None:
            raise ValueError("队列项不存在")

        if item.id == q.current_item_id:
            if q.status != "stopping":
                q.status = "stopping"
            last_run_id = item.last_run_id
            _record_history(db, item.id, item.task_id, "canceled", item.last_run_id, {"reason": "stop-and-delete"})
            db.commit()
            stopping = True
        else:
            _record_history(db, item.id, item.task_id, "removed", detail={"reason": "user-delete"})
            db.delete(item)
            db.commit()
            stopping = False
    if last_run_id:
        cancel_benchmark(last_run_id)
    get_scheduler().notify()
    return {"ok": True, "stopping": stopping}


def stop_queue(db: Session) -> dict[str, Any]:
    last_run_id: str | None = None
    with _queue_lock:
        q = _ensure_queue_row(db)
        if q.status not in ("running", "stopping"):
            raise ValueError(f"队列当前状态为 {q.status}，无法停止")
        q.status = "stopping_queue"
        if q.current_item_id:
            item = db.get(TaskQueueItem, q.current_item_id)
            if item and item.last_run_id:
                last_run_id = item.last_run_id
        _record_history(db, q.current_item_id, "", "stop_queue", detail={})
        db.commit()
        result = serialize_queue(db, q)
    if last_run_id:
        cancel_benchmark(last_run_id)
    get_scheduler().notify()
    return result


def reset_queue(db: Session) -> dict[str, Any]:
    with _queue_lock:
        q = _ensure_queue_row(db)
        prev = q.status
        if q.status != "error":
            raise ValueError(f"队列当前状态为 {q.status}，仅 error 态可复位")
        q.status = "idle"
        db.commit()
        result = serialize_queue(db, q)
    get_scheduler().reset_diagnostics()
    logger.info("queue.reset", extra={"prev_status": prev})
    get_scheduler().notify()
    return result


def recover_on_startup() -> None:
    db = SessionLocal()
    try:
        _recover_queue_current_item(db)
        _recover_standalone_benchmarks(db)
        _recover_downloads(db)
    finally:
        db.close()


def _recover_queue_current_item(db: Session) -> None:
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


def _recover_standalone_benchmarks(db: Session) -> None:
    jobs = db.scalars(
        select(BenchmarkJob).where(BenchmarkJob.status.in_(("running", "queued")))
    ).all()
    now = datetime.now(timezone.utc)
    for job in jobs:
        job.status = "failed"
        job.error = "interrupted by restart"
        job.finished_at = now
    if jobs:
        db.commit()
        logger.warning("benchmark.recovered", extra={"count": len(jobs)})


def _recover_downloads(db: Session) -> None:
    jobs = db.scalars(
        select(DownloadJob).where(DownloadJob.status.in_(("running", "queued")))
    ).all()
    now = datetime.now(timezone.utc)
    for job in jobs:
        job.status = "failed"
        job.error = "interrupted by restart"
        job.finished_at = now
        try:
            target = Path(job.target_path)
            part_path = target.with_suffix(target.suffix + ".part")
            part_path.unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("download.part_cleanup_failed", extra={"job_id": job.id, "error": str(exc)})
    if jobs:
        db.commit()
        logger.warning("download.recovered", extra={"count": len(jobs)})


class QueueScheduler:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._thread = threading.Thread(target=self._loop, name="llamalens-queue-scheduler", daemon=True)
        self._running = False
        self._consecutive_failures = 0
        self._last_error: str | None = None
        self._last_error_at: datetime | None = None
        self._pre_error_status: str | None = None
        self._failure_threshold = _failure_threshold()
        self._error_cooldown_s = _error_cooldown_seconds()
        self._subscribers: list[queue.Queue] = []
        self._sub_lock = threading.Lock()

    def start(self) -> None:
        if self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="llamalens-queue-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self.notify()

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def notify(self) -> None:
        with self._condition:
            self._condition.notify_all()
        self._publish()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=_sse_queue_maxsize())
        with self._sub_lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._sub_lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def _publish(self) -> None:
        with self._sub_lock:
            subs = list(self._subscribers)
        for sub in subs:
            try:
                sub.put_nowait(None)
            except queue.Full:
                pass

    def diagnostics(self) -> dict[str, Any]:
        return {
            "consecutive_failures": self._consecutive_failures,
            "last_error": self._last_error,
            "last_error_at": self._last_error_at,
            "failure_threshold": self._failure_threshold,
        }

    def reset_diagnostics(self) -> None:
        self._consecutive_failures = 0
        self._last_error = None
        self._last_error_at = None
        self._pre_error_status = None

    def _loop(self) -> None:
        while self._running:
            try:
                if self._consecutive_failures >= self._failure_threshold:
                    self._attempt_error_recovery()
                did_work = self._tick()
                if did_work:
                    self._on_tick_success()
            except Exception as exc:
                self._handle_tick_failure(exc)
            with self._condition:
                in_error = self._consecutive_failures >= self._failure_threshold
                wait_s = self._error_cooldown_s if in_error else 1.0
                self._condition.wait(timeout=wait_s)

    def _on_tick_success(self) -> None:
        if self._consecutive_failures == 0:
            return
        recovered = self._consecutive_failures >= self._failure_threshold
        self._consecutive_failures = 0
        self._last_error = None
        self._last_error_at = None
        self._pre_error_status = None
        if recovered:
            logger.info("queue.error_recovered", extra={"consecutive_failures": 0})

    def _handle_tick_failure(self, exc: BaseException) -> None:
        self._consecutive_failures += 1
        self._last_error = _format_error(exc)
        self._last_error_at = datetime.now(timezone.utc)
        logger.exception("queue.tick_failed", extra={
            "consecutive_failures": self._consecutive_failures,
        })
        if self._consecutive_failures >= self._failure_threshold:
            self._persist_error_state()

    def _persist_error_state(self) -> None:
        db = SessionLocal()
        try:
            with _queue_lock:
                q = db.get(TaskQueue, 1)
                if q is not None and q.status != "error":
                    self._pre_error_status = q.status
                    q.status = "error"
                    db.commit()
                    logger.error("queue.error_state_entered", extra={
                        "consecutive_failures": self._consecutive_failures,
                        "threshold": self._failure_threshold,
                        "prev_status": self._pre_error_status,
                    })
        finally:
            db.close()

    def _attempt_error_recovery(self) -> None:
        db = SessionLocal()
        try:
            with _queue_lock:
                q = db.get(TaskQueue, 1)
                if q is not None and q.status == "error":
                    target = self._pre_error_status or "running"
                    q.status = target
                    db.commit()
                    logger.info("queue.error_recover_attempt", extra={"to": target})
        finally:
            db.close()

    def _tick(self) -> bool:
        job_id: str | None = None
        need_run = False
        db = SessionLocal()
        try:
            with _queue_lock:
                q = _ensure_queue_row(db)
                if q.status not in ("running", "stopping"):
                    return False

                if q.current_item_id is None and q.status == "running":
                    self._try_dispatch(db, q)

                if q.current_item_id is not None:
                    item = db.get(TaskQueueItem, q.current_item_id)
                    job_id = item.last_run_id if item else None
                    if job_id:
                        job = db.get(BenchmarkJob, job_id)
                        if job and job.status in ("succeeded", "failed", "cancelled"):
                            need_run = False
                        else:
                            need_run = True
        finally:
            db.close()

        if job_id and need_run:
            run_benchmark_job(job_id)

        if job_id:
            db = SessionLocal()
            try:
                with _queue_lock:
                    q = db.get(TaskQueue, 1)
                    if q and q.current_item_id is not None:
                        self._handle_run_finished(db, q)
            finally:
                db.close()
            self.notify()
        return True

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
            job = create_run_for_task(db, task, q.session_id, q.interval_ms, item.run_name)
        except Exception as exc:
            job = BenchmarkJob(
                id=str(uuid.uuid4()),
                name=(item.run_name if item.run_name else task.name),
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
        logger.info("queue.item_started", extra={
            "item_id": item.id, "task_id": item.task_id, "run_id": job.id,
        })

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
        logger.info("queue.item_finished", extra={
            "item_id": item.id, "task_id": item.task_id, "run_id": item.last_run_id,
            "status": run_status,
        })

        if q.status == "stopping_queue":
            item.status = "waiting"
            item.started_at = None
            item.last_run_id = None
            q.current_item_id = None
            q.status = "idle"
            q.next_dispatch_at = None
            db.commit()
            return

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
