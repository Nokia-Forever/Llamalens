import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ArgumentCatalog
from app.services.arguments import refresh_runtime_catalog, seed_builtin_catalog
from app.services.settings_service import get_settings


router = APIRouter(prefix="/arguments", tags=["arguments"])


@router.get("")
def list_arguments(
    q: str = "",
    category: str | None = None,
    supported_only: bool = False,
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    seed_builtin_catalog(db)
    statement = select(ArgumentCatalog)
    if q:
        pattern = f"%{q}%"
        statement = statement.where(
            or_(ArgumentCatalog.key.ilike(pattern), ArgumentCatalog.description.ilike(pattern), ArgumentCatalog.aliases_json.ilike(pattern))
        )
    if category:
        statement = statement.where(ArgumentCatalog.category == category)
    if supported_only:
        statement = statement.where(ArgumentCatalog.supported.is_(True))
    rows = db.scalars(statement.order_by(ArgumentCatalog.category, ArgumentCatalog.key).limit(limit)).all()
    return [
        {
            "id": row.id,
            "key": row.key,
            "aliases": json.loads(row.aliases_json),
            "value_hint": row.value_hint,
            "description": row.description,
            "category": row.category,
            "source": row.source,
            "supported": row.supported,
        }
        for row in rows
    ]


@router.post("/refresh")
def refresh_arguments(db: Session = Depends(get_db)):
    seed_builtin_catalog(db)
    return refresh_runtime_catalog(db, get_settings(db))


@router.get("/categories")
def categories(db: Session = Depends(get_db)):
    seed_builtin_catalog(db)
    return sorted(set(db.scalars(select(ArgumentCatalog.category)).all()))
