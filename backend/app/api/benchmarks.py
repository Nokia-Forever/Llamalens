import json
import statistics

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import BenchmarkAttempt, BenchmarkJob
from app.schemas import BenchmarkBulkDelete, BenchmarkCreate
from app.services.benchmark import benchmark_service_unit, cancel_benchmark, create_benchmark_job, extract_output_text


router = APIRouter(prefix="/benchmarks", tags=["benchmarks"])
DELETABLE_STATUSES = {"succeeded", "failed", "cancelled"}


def _serialize(job: BenchmarkJob, include_attempts: bool = False):
    config = json.loads(job.config_json)
    summary = json.loads(job.summary_json)
    metrics = summary.get("metrics", {})
    successful_attempts = [attempt for attempt in job.attempts if not attempt.warmup and attempt.status == "succeeded"]
    for key, values in {
        "ttft_ms": [attempt.ttft_ms for attempt in successful_attempts],
        "prefill_tps": [attempt.prefill_tps for attempt in successful_attempts],
        "decode_tps": [attempt.decode_tps for attempt in successful_attempts],
        "client_decode_tps": [attempt.client_decode_tps for attempt in successful_attempts],
        "total_ms": [attempt.total_ms for attempt in successful_attempts],
    }.items():
        metric = metrics.setdefault(key, {})
        if "average" not in metric:
            values = [value for value in values if value is not None]
            metric["average"] = statistics.fmean(values) if values else None
    service_snapshot = config.get("service_snapshot")
    if isinstance(service_snapshot, dict) and "unit_content" in service_snapshot:
        service_snapshot = dict(service_snapshot)
        service_snapshot["has_unit_snapshot"] = bool(service_snapshot.pop("unit_content", ""))
        config["service_snapshot"] = service_snapshot
    result = {
        "id": job.id,
        "name": job.name,
        "service_id": job.service_id,
        "model_alias": job.model_alias,
        "profile_id": job.profile_id,
        "status": job.status,
        "config": config,
        "summary": summary,
        "error": job.error,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }
    if include_attempts:
        result["attempts"] = [
            {
                "id": attempt.id,
                "ordinal": attempt.ordinal,
                "warmup": attempt.warmup,
                "status": attempt.status,
                "measurement_mode": attempt.measurement_mode,
                "ttft_ms": attempt.ttft_ms,
                "prefill_tps": attempt.prefill_tps,
                "decode_tps": attempt.decode_tps,
                "client_decode_tps": attempt.client_decode_tps,
                "total_ms": attempt.total_ms,
                "prompt_tokens": attempt.prompt_tokens,
                "predicted_tokens": attempt.predicted_tokens,
                "resource": json.loads(attempt.resource_json),
                "error": attempt.error,
            }
            for attempt in sorted(job.attempts, key=lambda item: item.ordinal)
        ]
    return result


def _attempt_detail(attempt: BenchmarkAttempt):
    raw_response = json.loads(attempt.raw_response_json)
    return {
        "id": attempt.id,
        "job_id": attempt.job_id,
        "ordinal": attempt.ordinal,
        "warmup": attempt.warmup,
        "status": attempt.status,
        "measurement_mode": attempt.measurement_mode,
        "ttft_ms": attempt.ttft_ms,
        "prefill_tps": attempt.prefill_tps,
        "decode_tps": attempt.decode_tps,
        "client_decode_tps": attempt.client_decode_tps,
        "total_ms": attempt.total_ms,
        "prompt_tokens": attempt.prompt_tokens,
        "predicted_tokens": attempt.predicted_tokens,
        "request": json.loads(attempt.request_json),
        "response": raw_response,
        "output_text": extract_output_text(raw_response),
        "resource": json.loads(attempt.resource_json),
        "error": attempt.error,
        "created_at": attempt.created_at,
    }


def _deletable_jobs(db: Session, ids: list[str]) -> tuple[list[str], list[BenchmarkJob]]:
    unique_ids = list(dict.fromkeys(ids))
    jobs = db.scalars(select(BenchmarkJob).where(BenchmarkJob.id.in_(unique_ids))).all()
    found = {job.id for job in jobs}
    missing = [job_id for job_id in unique_ids if job_id not in found]
    if missing:
        raise HTTPException(status_code=404, detail=f"Benchmark 不存在: {', '.join(missing)}")
    blocked = [job for job in jobs if job.status not in DELETABLE_STATUSES]
    if blocked:
        names = ", ".join(f"{job.name} ({job.status})" for job in blocked)
        raise HTTPException(status_code=409, detail=f"运行中或排队的 Benchmark 不能删除: {names}")
    return unique_ids, jobs


@router.post("")
def create(payload: BenchmarkCreate, db: Session = Depends(get_db)):
    try:
        return _serialize(create_benchmark_job(db, payload))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("")
def list_jobs(db: Session = Depends(get_db)):
    jobs = db.scalars(select(BenchmarkJob).order_by(BenchmarkJob.created_at.desc()).limit(200)).all()
    return [_serialize(job) for job in jobs]


@router.get("/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(BenchmarkJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Benchmark 不存在")
    return _serialize(job, include_attempts=True)


@router.get("/{job_id}/service-unit")
def get_service_unit(job_id: str, db: Session = Depends(get_db)):
    job = db.get(BenchmarkJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Benchmark 不存在")
    try:
        return benchmark_service_unit(db, job)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{job_id}/attempts/{attempt_id}")
def get_attempt(job_id: str, attempt_id: int, db: Session = Depends(get_db)):
    attempt = db.scalar(
        select(BenchmarkAttempt).where(BenchmarkAttempt.id == attempt_id, BenchmarkAttempt.job_id == job_id)
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail="Benchmark Attempt 不存在")
    return _attempt_detail(attempt)


@router.post("/{job_id}/cancel")
def cancel(job_id: str, db: Session = Depends(get_db)):
    if db.get(BenchmarkJob, job_id) is None:
        raise HTTPException(status_code=404, detail="Benchmark 不存在")
    cancel_benchmark(job_id)
    return {"ok": True}


@router.delete("/{job_id}")
def delete_job(job_id: str, db: Session = Depends(get_db)):
    ids, jobs = _deletable_jobs(db, [job_id])
    db.delete(jobs[0])
    db.commit()
    return {"ok": True, "deleted_ids": ids}


@router.post("/bulk-delete")
def bulk_delete(payload: BenchmarkBulkDelete, db: Session = Depends(get_db)):
    ids, jobs = _deletable_jobs(db, payload.ids)
    for job in jobs:
        db.delete(job)
    db.commit()
    return {"ok": True, "deleted_ids": ids}
