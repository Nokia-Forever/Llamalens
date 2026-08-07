from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import ArgumentCatalog, LlamaService, Profile, ProfileVersion
from app.schemas import AppSettings, CatalogArgumentInput, ProfileCreate, ProfileOut
from app.services.arguments import build_profile_argv


def known_flags(db: Session) -> set[str]:
    flags: set[str] = set()
    for row in db.scalars(select(ArgumentCatalog).where(ArgumentCatalog.supported.is_(True))).all():
        flags.update(json.loads(row.aliases_json))
    return flags


def canonical_flags(db: Session) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in db.scalars(select(ArgumentCatalog).where(ArgumentCatalog.supported.is_(True))).all():
        for alias in json.loads(row.aliases_json):
            result[alias] = row.key
    return result


def _ensure_model_allowed(model_path: str, settings: AppSettings) -> str:
    path = Path(model_path).expanduser().resolve(strict=False)
    if path.suffix.lower() != ".gguf":
        raise ValueError("模型必须是 .gguf 文件")
    for root in settings.model_roots:
        try:
            path.relative_to(Path(root).expanduser().resolve(strict=False))
        except ValueError:
            continue
        if not path.is_file():
            raise ValueError("模型文件不存在或不是普通文件")
        return str(path)
    raise ValueError("模型路径不在设置的模型目录中")


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def create_profile(db: Session, settings: AppSettings, payload: ProfileCreate) -> Profile:
    service = db.get(LlamaService, payload.service_id) if payload.service_id else None
    if payload.service_id and service is None:
        raise ValueError("目标服务不存在")
    if service is not None:
        from app.services.llama_services import app_settings_for_service

        settings = app_settings_for_service(service, settings)
    model_path = _ensure_model_allowed(payload.model_path, settings)
    build_profile_argv(
        settings, model_path, payload.catalog_args, payload.custom_args_text, known_flags(db), canonical_flags(db)
    )
    profile = Profile(
        id=str(uuid.uuid4()),
        service_id=payload.service_id,
        model_alias=payload.model_alias or (service.model_alias if service is not None else ""),
        name=payload.name,
        model_path=model_path,
        catalog_args_json=json.dumps([item.model_dump() for item in payload.catalog_args], ensure_ascii=False),
        custom_args_text=payload.custom_args_text,
        labels_json=json.dumps(payload.labels, ensure_ascii=False),
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def update_profile(db: Session, settings: AppSettings, profile: Profile, payload: ProfileCreate) -> Profile:
    service = db.get(LlamaService, payload.service_id) if payload.service_id else None
    if payload.service_id and service is None:
        raise ValueError("目标服务不存在")
    if service is not None:
        from app.services.llama_services import app_settings_for_service

        settings = app_settings_for_service(service, settings)
    model_path = _ensure_model_allowed(payload.model_path, settings)
    build_profile_argv(
        settings, model_path, payload.catalog_args, payload.custom_args_text, known_flags(db), canonical_flags(db)
    )
    profile.service_id = payload.service_id
    profile.model_alias = payload.model_alias or (service.model_alias if service is not None else "")
    profile.name = payload.name
    profile.model_path = model_path
    profile.catalog_args_json = json.dumps([item.model_dump() for item in payload.catalog_args], ensure_ascii=False)
    profile.custom_args_text = payload.custom_args_text
    profile.labels_json = json.dumps(payload.labels, ensure_ascii=False)
    db.commit()
    db.refresh(profile)
    return profile


def serialize_profile(db: Session, settings: AppSettings, profile: Profile) -> ProfileOut:
    service = db.get(LlamaService, profile.service_id) if profile.service_id else None
    if service is not None:
        from app.services.llama_services import app_settings_for_service

        settings = app_settings_for_service(service, settings)
    catalog_args = [CatalogArgumentInput.model_validate(item) for item in json.loads(profile.catalog_args_json)]
    built = build_profile_argv(
        settings, profile.model_path, catalog_args, profile.custom_args_text, known_flags(db), canonical_flags(db)
    )
    return ProfileOut(
        id=profile.id,
        service_id=profile.service_id,
        model_alias=profile.model_alias,
        name=profile.name,
        model_path=profile.model_path,
        catalog_args=catalog_args,
        custom_args_text=profile.custom_args_text,
        labels=json.loads(profile.labels_json),
        is_active=profile.is_active,
        final_argv=built.argv,
        warnings=built.warnings,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def write_active_profile(db: Session, settings: AppSettings, profile: Profile, binary_version: str | None = None) -> ProfileVersion:
    serialized = serialize_profile(db, settings, profile)
    version = ProfileVersion(
        id=str(uuid.uuid4()),
        profile_id=profile.id,
        spec_json=serialized.model_dump_json(),
        argv_json=json.dumps(serialized.final_argv, ensure_ascii=False),
        binary_version=binary_version,
    )
    active_path = Path(settings.active_profile_path).expanduser()
    content = json.dumps(
        {
            "profile_id": profile.id,
            "profile_version_id": version.id,
            "argv": serialized.final_argv,
            "spec": serialized.model_dump(mode="json"),
        },
        ensure_ascii=False,
        indent=2,
    )
    atomic_write_text(active_path, content)
    if profile.service_id is None:
        db.execute(update(Profile).where(Profile.service_id.is_(None)).values(is_active=False))
    else:
        db.execute(update(Profile).where(Profile.service_id == profile.service_id).values(is_active=False))
    profile.is_active = True
    db.add(version)
    db.commit()
    return version
