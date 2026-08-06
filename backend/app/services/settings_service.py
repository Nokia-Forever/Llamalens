from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models import SettingsRecord
from app.schemas import AppSettings


def get_settings(db: Session) -> AppSettings:
    record = db.get(SettingsRecord, 1)
    if record is None:
        settings = AppSettings()
        db.add(SettingsRecord(id=1, payload_json=settings.model_dump_json()))
        db.commit()
        return settings
    return AppSettings.model_validate_json(record.payload_json)


def save_settings(db: Session, settings: AppSettings) -> AppSettings:
    record = db.get(SettingsRecord, 1)
    payload = json.dumps(settings.model_dump(), ensure_ascii=False)
    if record is None:
        record = SettingsRecord(id=1, payload_json=payload)
        db.add(record)
    else:
        record.payload_json = payload
    db.commit()
    return settings
