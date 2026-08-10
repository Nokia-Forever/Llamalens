from __future__ import annotations

import json
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BenchmarkJob, BenchmarkTask, LlamaService
from app.schemas import TaskCreate, TaskOut, TaskUpdate
from app.services.llama_services import launch_aliases
from app.schemas import LaunchConfig


_BENCHMARK_PARAM_KEYS = (
    "prompt", "max_tokens", "timeout_seconds", "temperature", "seed", "stop",
    "cache_prompt", "warmup_runs", "repeat_runs", "repeat_delay_ms", "concurrency", "extra_params",
)


def _validate_service_and_alias(db: Session, service_id: str, model_alias: str) -> None:
    service = db.get(LlamaService, service_id)
    if service is None or service.archived_at is not None:
        raise ValueError("目标服务不存在或已归档")
    if not service.applied_launch_config_json:
        raise ValueError("目标服务尚未成功部署，没有可测试的 applied 配置")
    applied = LaunchConfig.model_validate_json(service.applied_launch_config_json)
    aliases = set(launch_aliases(applied))
    if not model_alias or model_alias not in aliases:
        raise ValueError("请选择目标服务已部署配置中的模型 alias")


def _task_to_config_dict(task: BenchmarkTask) -> dict[str, object]:
    stored = json.loads(task.config_json)
    return {key: stored.get(key) for key in _BENCHMARK_PARAM_KEYS}


def serialize_task(task: BenchmarkTask) -> TaskOut:
    return TaskOut(
        id=task.id,
        name=task.name,
        service_id=task.service_id,
        model_alias=task.model_alias,
        config=_task_to_config_dict(task),
        last_run_status=task.last_run_status,
        run_count=task.run_count,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def list_tasks(db: Session) -> list[BenchmarkTask]:
    return db.scalars(select(BenchmarkTask).order_by(BenchmarkTask.updated_at.desc())).all()


def get_task(db: Session, task_id: str) -> BenchmarkTask | None:
    return db.get(BenchmarkTask, task_id)


def get_recent_runs(db: Session, task_id: str, limit: int = 20) -> list[BenchmarkJob]:
    return db.scalars(
        select(BenchmarkJob)
        .where(BenchmarkJob.task_id == task_id)
        .order_by(BenchmarkJob.created_at.desc())
        .limit(limit)
    ).all()


def create_task(db: Session, payload: TaskCreate) -> BenchmarkTask:
    _validate_service_and_alias(db, payload.service_id, payload.model_alias)
    config = payload.model_dump(mode="json")
    for key in ("name", "service_id", "model_alias"):
        config.pop(key, None)
    task = BenchmarkTask(
        id=str(uuid.uuid4()),
        name=payload.name,
        service_id=payload.service_id,
        model_alias=payload.model_alias,
        config_json=json.dumps(config, ensure_ascii=False),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def update_task(db: Session, task: BenchmarkTask, payload: TaskUpdate) -> BenchmarkTask:
    _validate_service_and_alias(db, payload.service_id, payload.model_alias)
    config = payload.model_dump(mode="json")
    for key in ("name", "service_id", "model_alias"):
        config.pop(key, None)
    task.name = payload.name
    task.service_id = payload.service_id
    task.model_alias = payload.model_alias
    task.config_json = json.dumps(config, ensure_ascii=False)
    db.commit()
    db.refresh(task)
    return task


def delete_task(db: Session, task: BenchmarkTask) -> None:
    db.delete(task)
    db.commit()
