from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DownloadJob, ModelFile
from app.schemas import DownloadCreate
from app.services.models_service import cancel_download, create_download, scan_models, search_huggingface
from app.services.settings_service import get_settings


router = APIRouter(prefix="/models", tags=["models"])


def _model_dict(row: ModelFile):
    return {
        "id": row.id,
        "path": row.path,
        "name": row.name,
        "size_bytes": row.size_bytes,
        "quantization": row.quantization,
        "modified_at": row.modified_at,
        "available": row.available,
        "scanned_at": row.scanned_at,
    }


@router.get("")
def list_models(
    q: str = "",
    available_only: bool = True,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    statement = select(ModelFile)
    if q:
        statement = statement.where((ModelFile.name.ilike(f"%{q}%")) | (ModelFile.path.ilike(f"%{q}%")))
    if available_only:
        statement = statement.where(ModelFile.available.is_(True))
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    rows = db.scalars(statement.order_by(ModelFile.name).offset(offset).limit(limit)).all()
    return {"items": [_model_dict(row) for row in rows], "total": total, "offset": offset, "limit": limit}


@router.post("/scan")
def scan(db: Session = Depends(get_db)):
    settings = get_settings(db)
    return scan_models(db, settings.model_roots)


@router.get("/remote-search")
def remote_search(q: str = Query(min_length=2), limit: int = Query(20, ge=1, le=50)):
    try:
        return search_huggingface(q, limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Hugging Face 搜索失败: {exc}") from exc


@router.post("/downloads")
def start_download(payload: DownloadCreate, db: Session = Depends(get_db)):
    try:
        job = create_download(db, get_settings(db), payload)
        return {"id": job.id, "status": job.status, "target_path": job.target_path}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/downloads")
def list_downloads(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    base = select(DownloadJob).order_by(DownloadJob.created_at.desc())
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.scalars(base.offset(offset).limit(limit)).all()
    return {
        "items": [
            {
                "id": row.id,
                "url": row.url,
                "target_path": row.target_path,
                "status": row.status,
                "downloaded_bytes": row.downloaded_bytes,
                "total_bytes": row.total_bytes,
                "error": row.error,
                "created_at": row.created_at,
                "finished_at": row.finished_at,
            }
            for row in rows
        ],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.post("/downloads/{job_id}/cancel")
def cancel(job_id: str, db: Session = Depends(get_db)):
    if db.get(DownloadJob, job_id) is None:
        raise HTTPException(status_code=404, detail="下载任务不存在")
    cancel_download(job_id)
    return {"ok": True}
