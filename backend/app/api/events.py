from __future__ import annotations

import asyncio
import functools
import json
import os
import queue

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.auth import verify_auth_query
from app.database import SessionLocal
from app.services.task_queue import _ensure_queue_row, get_scheduler, serialize_queue


router = APIRouter(prefix="/events", tags=["events"], dependencies=[Depends(verify_auth_query)])


def _keepalive_seconds() -> float:
    try:
        return max(1.0, float(os.getenv("LLAMALENS_SSE_KEEPALIVE_S", "5")))
    except ValueError:
        return 5.0


async def _event_stream(request: Request):
    scheduler = get_scheduler()
    q = scheduler.subscribe()
    try:
        db = SessionLocal()
        try:
            row = _ensure_queue_row(db)
            payload = serialize_queue(db, row)
        finally:
            db.close()
        yield f"event: queue\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"

        while True:
            if await request.is_disconnected():
                break
            try:
                await asyncio.wait_for(
                    asyncio.get_running_loop().run_in_executor(
                        None, functools.partial(q.get, timeout=_keepalive_seconds())
                    ),
                    timeout=10,
                )
            except (asyncio.TimeoutError, queue.Empty):
                yield ": keepalive\n\n"
                continue

            db = SessionLocal()
            try:
                row = _ensure_queue_row(db)
                payload = serialize_queue(db, row)
            finally:
                db.close()
            yield f"event: queue\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
    finally:
        scheduler.unsubscribe(q)


@router.get("/queue")
async def stream_queue(request: Request):
    return StreamingResponse(
        _event_stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


__all__ = ["router"]
