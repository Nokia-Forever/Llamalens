import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import BenchmarkJob
from app.schemas import BenchmarkCreate
from app.services.benchmark import cancel_benchmark, create_benchmark_job


router = APIRouter(prefix="/benchmarks", tags=["benchmarks"])


def _serialize(job: BenchmarkJob, include_attempts: bool = False):
    result = {
        "id": job.id,
        "name": job.name,
        "profile_id": job.profile_id,
        "status": job.status,
        "config": json.loads(job.config_json),
        "summary": json.loads(job.summary_json),
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


@router.post("/{job_id}/cancel")
def cancel(job_id: str, db: Session = Depends(get_db)):
    if db.get(BenchmarkJob, job_id) is None:
        raise HTTPException(status_code=404, detail="Benchmark 不存在")
    cancel_benchmark(job_id)
    return {"ok": True}
