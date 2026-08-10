import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import TaskQueueHistory
from app.schemas import QueueItemCreate, QueuePatch, ReorderInput
from app.services import task_queue

router = APIRouter(prefix="/queue", tags=["queue"])


@router.get("")
def get_queue(db: Session = Depends(get_db)):
    return task_queue.get_queue_state(db)


@router.patch("")
def patch_queue(payload: QueuePatch, db: Session = Depends(get_db)):
    try:
        if payload.interval_ms is not None or payload.cancel_timeout_ms is not None:
            task_queue.update_queue_settings(db, payload.interval_ms, payload.cancel_timeout_ms)
        if payload.status == "start":
            return task_queue.start_queue(db)
        elif payload.status == "pause":
            return task_queue.pause_queue(db)
        return task_queue.get_queue_state(db)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/items")
def add_item(payload: QueueItemCreate, db: Session = Depends(get_db)):
    try:
        return task_queue.enqueue_item(db, payload.task_id, payload.position, payload.run_name)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/items/reorder")
def reorder(payload: ReorderInput, db: Session = Depends(get_db)):
    try:
        task_queue.reorder_items(db, payload.item_ids)
        return task_queue.get_queue_state(db)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/items/{item_id}")
def remove_item(item_id: str, db: Session = Depends(get_db)):
    try:
        return task_queue.delete_item(db, item_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/history")
def get_history(db: Session = Depends(get_db)):
    history = db.scalars(
        select(TaskQueueHistory).order_by(TaskQueueHistory.at.desc()).limit(200)
    ).all()
    return [
        {
            "id": h.id,
            "item_id": h.item_id,
            "task_id": h.task_id,
            "action": h.action,
            "run_id": h.run_id,
            "detail": json.loads(h.detail_json) if h.detail_json else {},
            "at": h.at,
        }
        for h in history
    ]
