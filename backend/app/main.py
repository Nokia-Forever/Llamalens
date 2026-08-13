from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import arguments, auth, benchmarks, events, models, profiles, queue, services, settings, system, tasks
from app.database import SessionLocal, get_db, init_db
from app.logging_config import get_logger, setup_logging
from app.services.arguments import seed_builtin_catalog
from app.services.auth_service import bootstrap_from_env
from app.services.llama_services import migrate_legacy_service
from app.services.settings_service import get_settings
from app.services import task_queue


logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    logger.info("lifespan.starting")
    init_db()
    db = SessionLocal()
    try:
        seed_builtin_catalog(db)
        migrate_legacy_service(db, get_settings(db))
        if bootstrap_from_env(db):
            logger.info("auth.token_bootstrapped")
    finally:
        db.close()
    task_queue.recover_on_startup()
    task_queue.get_scheduler().start()
    logger.info("lifespan.started")
    yield
    logger.info("lifespan.stopping")
    task_queue.get_scheduler().stop()
    logger.info("lifespan.stopped")


app = FastAPI(title="LlamaLens API", version="0.1.0", lifespan=lifespan)
cors_origins = [
    item.strip()
    for item in os.getenv(
        "LLAMALENS_CORS_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:3000,http://localhost:3000",
    ).split(",")
    if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def uncaught_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("uncaught_exception", extra={"path": request.url.path})
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


def _db_ping(db: Session) -> str:
    try:
        db.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        logger.exception("health.db_ping_failed")
        return "fail"


@app.get("/api/v1/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    return {"status": "ok", "db": _db_ping(db)}


@app.get("/api/v1/ready")
def ready(db: Session = Depends(get_db)) -> dict[str, object]:
    db_status = _db_ping(db)
    scheduler = task_queue.get_scheduler()
    scheduler_alive = scheduler.is_alive()
    diag = scheduler.diagnostics()
    queue_diag = task_queue.get_queue_diagnostics(db)
    queue_status = queue_diag["queue_status"]
    scheduler_failures = diag["consecutive_failures"]
    healthy = db_status == "ok" and scheduler_alive and queue_status != "error" and scheduler_failures == 0
    status = "ready" if healthy else "degraded"
    return {
        "status": status,
        "checks": {
            "db": db_status,
            "scheduler_alive": scheduler_alive,
            "queue_status": queue_status,
            "scheduler_failures": scheduler_failures,
        },
    }


app.include_router(auth.router, prefix="/api/v1")

API_ROUTERS = [
    settings.router, system.router, services.router, arguments.router, models.router,
    profiles.router, benchmarks.router, tasks.router, queue.router,
]
for router in API_ROUTERS:
    app.include_router(router, prefix="/api/v1", dependencies=[Depends(auth.verify_auth)])

app.include_router(events.router, prefix="/api/v1")


frontend_dist = Path(os.getenv("LLAMALENS_FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist"))
if frontend_dist.is_dir() and (frontend_dist / "index.html").is_file():
    assets_dir = frontend_dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def frontend(full_path: str):
        candidate = (frontend_dist / full_path).resolve(strict=False)
        try:
            candidate.relative_to(frontend_dist.resolve())
        except ValueError:
            return FileResponse(frontend_dist / "index.html")
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(frontend_dist / "index.html")
