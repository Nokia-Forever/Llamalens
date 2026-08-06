from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import AppSettings
from app.services.settings_service import get_settings, save_settings
from app.services.systemd import probe_binary, run_service_action


router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=AppSettings)
def read_settings(db: Session = Depends(get_db)):
    return get_settings(db)


@router.put("", response_model=AppSettings)
def update_settings(payload: AppSettings, db: Session = Depends(get_db)):
    return save_settings(db, payload)


@router.get("/probe")
def probe_settings(db: Session = Depends(get_db)):
    settings = get_settings(db)
    status = run_service_action(settings, "status")
    return {"binary": probe_binary(settings), "service": status.__dict__}
