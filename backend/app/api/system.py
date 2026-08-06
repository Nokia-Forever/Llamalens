from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import BenchmarkJob, Profile, SwitchJob
from app.schemas import ServiceAction
from app.services.settings_service import get_settings
from app.services.systemd import probe_binary, read_journal, run_service_action


router = APIRouter(prefix="/system", tags=["system"])


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    settings = get_settings(db)
    status = run_service_action(settings, "status")
    active = db.scalar(select(Profile).where(Profile.is_active.is_(True)))
    recent_benchmarks = db.scalars(select(BenchmarkJob).order_by(BenchmarkJob.created_at.desc()).limit(5)).all()
    recent_switches = db.scalars(select(SwitchJob).order_by(SwitchJob.created_at.desc()).limit(5)).all()
    return {
        "service": status.__dict__,
        "binary": probe_binary(settings),
        "active_profile": {"id": active.id, "name": active.name, "model_path": active.model_path} if active else None,
        "recent_benchmarks": [
            {"id": job.id, "name": job.name, "status": job.status, "created_at": job.created_at} for job in recent_benchmarks
        ],
        "recent_switches": [
            {"id": job.id, "profile_id": job.profile_id, "status": job.status, "message": job.message}
            for job in recent_switches
        ],
    }


@router.post("/action")
def service_action(payload: ServiceAction, db: Session = Depends(get_db)):
    result = run_service_action(get_settings(db), payload.action)
    return result.__dict__


@router.get("/logs")
def logs(lines: int = Query(200, ge=1, le=500), db: Session = Depends(get_db)):
    return read_journal(get_settings(db), lines).__dict__
