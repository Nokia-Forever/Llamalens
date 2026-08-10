from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import arguments, benchmarks, models, profiles, queue, services, settings, system, tasks
from app.database import SessionLocal, init_db
from app.services.arguments import seed_builtin_catalog
from app.services.llama_services import migrate_legacy_service
from app.services.settings_service import get_settings
from app.services import task_queue


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        seed_builtin_catalog(db)
        migrate_legacy_service(db, get_settings(db))
    finally:
        db.close()
    task_queue.recover_on_startup()
    task_queue.get_scheduler().start()
    yield
    task_queue.get_scheduler().stop()


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


@app.get("/api/v1/health")
def health():
    return {"status": "ok"}


for router in [settings.router, system.router, services.router, arguments.router, models.router, profiles.router, benchmarks.router, tasks.router, queue.router]:
    app.include_router(router, prefix="/api/v1")


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
