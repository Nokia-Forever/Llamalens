from __future__ import annotations

import uvicorn

from app.database import SessionLocal, init_db
from app.services.settings_service import get_settings


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        settings = get_settings(db)
        host = settings.web_host
        port = settings.web_port
    finally:
        db.close()
    uvicorn.run("app.main:app", host=host, port=port, proxy_headers=True)


if __name__ == "__main__":
    main()
