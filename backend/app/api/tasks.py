import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import TaskQueue, TaskQueueItem
from app.schemas import TaskCreate, TaskUpdate
from app.services import task_service

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("")
def list_tasks(db: Session = Depends(get_db)):
    return [task_service.serialize_task(task).model_dump(mode="json") for task in task_service.list_tasks(db)]


@router.post("")
def create(payload: TaskCreate, db: Session = Depends(get_db)):
    try:
        return task_service.serialize_task(task_service.create_task(db, payload)).model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{task_id}")
def get_task(task_id: str, db: Session = Depends(get_db)):
    task = task_service.get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    result = task_service.serialize_task(task).model_dump(mode="json")
    result["recent_runs"] = [
        {
            "id": job.id,
            "status": job.status,
            "name": job.name,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "summary": json.loads(job.summary_json) if job.summary_json else {},
            "error": job.error,
        }
        for job in task_service.get_recent_runs(db, task_id)
    ]
    return result


@router.patch("/{task_id}")
def update(task_id: str, payload: TaskUpdate, db: Session = Depends(get_db)):
    task = task_service.get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    try:
        return task_service.serialize_task(task_service.update_task(db, task, payload)).model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/{task_id}")
def delete(task_id: str, db: Session = Depends(get_db)):
    task = task_service.get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    q = db.get(TaskQueue, 1)
    if q and q.current_item_id:
        current_item = db.get(TaskQueueItem, q.current_item_id)
        if current_item and current_item.task_id == task_id:
            raise HTTPException(status_code=409, detail="该任务正在队列中执行，请先在队列页面停止并删除")
    task_service.delete_task(db, task)
    return {"ok": True}
