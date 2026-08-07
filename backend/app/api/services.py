from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import LlamaService
from app.schemas import LlamaServiceCreate, LlamaServiceUpdate, ServiceAction
from app.services.llama_services import (
    archive_service,
    create_service,
    delete_service,
    deploy_service,
    render_unit,
    restore_service,
    serialize_service,
    service_logs,
    update_service,
)
from app.services.systemd import run_unit_action


router = APIRouter(prefix="/services", tags=["services"])


def _get(db: Session, service_id: str) -> LlamaService:
    row = db.get(LlamaService, service_id)
    if row is None:
        raise HTTPException(status_code=404, detail="服务不存在")
    return row


@router.post("/preview-unit")
def preview_unit(payload: LlamaServiceCreate):
    try:
        return render_unit(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("")
def list_services(include_archived: bool = False, with_status: bool = False, db: Session = Depends(get_db)):
    statement = select(LlamaService).order_by(LlamaService.created_at.desc())
    if not include_archived:
        statement = statement.where(LlamaService.archived_at.is_(None))
    return [serialize_service(row, status=with_status) for row in db.scalars(statement).all()]


@router.post("")
def add_service(payload: LlamaServiceCreate, db: Session = Depends(get_db)):
    try:
        return serialize_service(create_service(db, payload))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{service_id}")
def get_service(service_id: str, db: Session = Depends(get_db)):
    return serialize_service(_get(db, service_id), status=True)


@router.patch("/{service_id}")
def edit_service(service_id: str, payload: LlamaServiceUpdate, db: Session = Depends(get_db)):
    try:
        return serialize_service(update_service(db, _get(db, service_id), payload))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{service_id}/deploy")
def deploy(service_id: str, db: Session = Depends(get_db)):
    row = _get(db, service_id)
    if row.archived_at is not None:
        raise HTTPException(status_code=409, detail="归档服务不能直接部署，请先恢复")
    return deploy_service(row)


@router.post("/{service_id}/action")
def action(service_id: str, payload: ServiceAction, db: Session = Depends(get_db)):
    row = _get(db, service_id)
    if row.archived_at is not None:
        raise HTTPException(status_code=409, detail="归档服务不能执行运行操作")
    return run_unit_action(row.unit_name, payload.action, timeout=120).__dict__


@router.get("/{service_id}/logs")
def logs(service_id: str, lines: int = Query(200, ge=1, le=500), db: Session = Depends(get_db)):
    return service_logs(_get(db, service_id), lines)


@router.get("/{service_id}/models")
def models(service_id: str, db: Session = Depends(get_db)):
    row = _get(db, service_id)
    return [{"id": item.id, "alias": item.alias, "model_path": item.model_path, "display_name": item.display_name, "enabled": item.enabled} for item in row.models]


@router.post("/{service_id}/archive")
def archive(service_id: str, db: Session = Depends(get_db)):
    row = _get(db, service_id)
    if row.archived_at is not None:
        raise HTTPException(status_code=409, detail="服务已经归档")
    return archive_service(db, row)


@router.post("/{service_id}/restore")
def restore(service_id: str, db: Session = Depends(get_db)):
    row = _get(db, service_id)
    if row.archived_at is None:
        raise HTTPException(status_code=409, detail="服务未归档")
    conflict = db.scalar(
        select(LlamaService.id)
        .where(
            LlamaService.id != row.id,
            LlamaService.host == row.host,
            LlamaService.port == row.port,
            LlamaService.archived_at.is_(None),
        )
        .limit(1)
    )
    if conflict:
        raise HTTPException(status_code=409, detail="该 host/port 已被另一个服务使用")
    return restore_service(db, row)


@router.delete("/{service_id}")
def remove(service_id: str, db: Session = Depends(get_db)):
    return delete_service(db, _get(db, service_id))
