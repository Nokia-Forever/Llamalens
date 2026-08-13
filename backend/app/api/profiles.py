from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import BenchmarkJob, Profile, SwitchJob
from app.schemas import ProfileCreate, ProfileOut, ProfileUpdate
from app.services.profiles_service import canonical_flags, create_profile, known_flags, serialize_profile, update_profile
from app.services.settings_service import get_settings


router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get("")
def list_profiles(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    settings = get_settings(db)
    flags = (known_flags(db), canonical_flags(db))
    statement = select(Profile).order_by(Profile.updated_at.desc())
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    rows = db.scalars(statement.offset(offset).limit(limit)).all()
    return {"items": [serialize_profile(db, settings, row, flags=flags) for row in rows], "total": total, "offset": offset, "limit": limit}


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
    has_switches = db.scalar(select(SwitchJob.id).where(SwitchJob.profile_id == profile_id).limit(1)) is not None
    has_benchmarks = db.scalar(select(BenchmarkJob.id).where(BenchmarkJob.profile_id == profile_id).limit(1)) is not None
    if has_switches or has_benchmarks:
        raise HTTPException(status_code=409, detail="Profile 已有切换或 Benchmark 历史，为保持结果可追溯不能删除")
    db.delete(row)
    db.commit()
    return {"ok": True}
