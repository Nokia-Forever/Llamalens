import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import BenchmarkJob, Profile, SwitchJob
from app.schemas import ProfileCreate, ProfileOut, ProfileUpdate
from app.services.operations import create_switch_job
from app.services.profiles_service import create_profile, serialize_profile, update_profile
from app.services.settings_service import get_settings


router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get("", response_model=list[ProfileOut])
def list_profiles(db: Session = Depends(get_db)):
    settings = get_settings(db)
    return [serialize_profile(db, settings, row) for row in db.scalars(select(Profile).order_by(Profile.updated_at.desc())).all()]


@router.post("", response_model=ProfileOut)
def add_profile(payload: ProfileCreate, db: Session = Depends(get_db)):
    settings = get_settings(db)
    try:
        return serialize_profile(db, settings, create_profile(db, settings, payload))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{profile_id}", response_model=ProfileOut)
def get_profile(profile_id: str, db: Session = Depends(get_db)):
    row = db.get(Profile, profile_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Profile 不存在")
    return serialize_profile(db, get_settings(db), row)


@router.put("/{profile_id}", response_model=ProfileOut)
def edit_profile(profile_id: str, payload: ProfileUpdate, db: Session = Depends(get_db)):
    row = db.get(Profile, profile_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Profile 不存在")
    settings = get_settings(db)
    try:
        return serialize_profile(db, settings, update_profile(db, settings, row, payload))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{profile_id}")
def delete_profile(profile_id: str, db: Session = Depends(get_db)):
    row = db.get(Profile, profile_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Profile 不存在")
    if row.is_active:
        raise HTTPException(status_code=409, detail="不能删除当前激活 Profile")
    has_switches = db.scalar(select(SwitchJob.id).where(SwitchJob.profile_id == profile_id).limit(1)) is not None
    has_benchmarks = db.scalar(select(BenchmarkJob.id).where(BenchmarkJob.profile_id == profile_id).limit(1)) is not None
    if has_switches or has_benchmarks:
        raise HTTPException(status_code=409, detail="Profile 已有切换或 Benchmark 历史，为保持结果可追溯不能删除")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.post("/{profile_id}/activate")
def activate_profile(profile_id: str, db: Session = Depends(get_db)):
    if db.get(Profile, profile_id) is None:
        raise HTTPException(status_code=404, detail="Profile 不存在")
    busy = db.scalar(select(BenchmarkJob).where(BenchmarkJob.status.in_(["queued", "running"])).limit(1))
    if busy is not None:
        raise HTTPException(status_code=409, detail="Benchmark 正在排队或运行，完成后才能切换 Profile")
    job = create_switch_job(profile_id)
    return {"id": job.id, "status": job.status, "profile_id": job.profile_id}


@router.get("/switch-jobs/{job_id}")
def switch_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(SwitchJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="切换任务不存在")
    return {
        "id": job.id,
        "profile_id": job.profile_id,
        "status": job.status,
        "message": job.message,
        "diagnostics": json.loads(job.diagnostics_json),
        "created_at": job.created_at,
        "finished_at": job.finished_at,
    }
