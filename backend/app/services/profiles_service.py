from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ArgumentCatalog, Profile, ProfileModel, ProfileVersion
from app.schemas import AppSettings, CatalogArgumentInput, LaunchConfig, LaunchModelInput, ProfileCreate, ProfileOut
from app.services.arguments import build_server_argv


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


def _resolve_under_roots(path_value: str, settings: AppSettings, expected: str) -> str:
    path = Path(path_value).expanduser().resolve(strict=False)
    for root in settings.model_roots:
        try:
            path.relative_to(Path(root).expanduser().resolve(strict=False))
        except ValueError:
            continue
        if expected == "file" and not path.is_file():
            raise ValueError("模型文件不存在或不是普通文件")
        if expected == "directory" and not path.is_dir():
            raise ValueError("模型目录不存在或不是目录")
        return str(path)
    raise ValueError("模型路径不在设置的模型目录中")


def normalize_launch_config(settings: AppSettings, config: LaunchConfig) -> LaunchConfig:
    normalized = config.model_copy(deep=True)
    if normalized.mode == "single":
        normalized.model_path = _resolve_under_roots(normalized.model_path, settings, "file")
        normalized.models = []
    else:
        normalized.models_dir = _resolve_under_roots(normalized.models_dir, settings, "directory")
        normalized.models = [
            LaunchModelInput(
                alias=item.alias,
                model_path=_resolve_under_roots(item.model_path, settings, "file") if item.model_path else "",
                display_name=item.display_name,
                enabled=item.enabled,
            )
            for item in normalized.models
        ]
    return normalized


def launch_config_from_profile(profile: Profile) -> LaunchConfig:
    catalog_args = [CatalogArgumentInput.model_validate(item) for item in json.loads(profile.catalog_args_json)]
    models = [
        LaunchModelInput(alias=item.alias, model_path=item.model_path, display_name=item.display_name, enabled=item.enabled)
        for item in profile.models
    ]
    alias = profile.model_alias.strip() or re.sub(r"[^A-Za-z0-9_.@-]+", "-", profile.name).strip("-").lower() or "model"
    return LaunchConfig(
        mode=profile.mode or "single",
        model_path=profile.model_path,
        model_alias=alias,
        models_dir=profile.models_dir,
        models_preset=profile.models_preset,
        models_max=profile.models_max,
        models_autoload=profile.models_autoload,
        models=models,
        catalog_args=catalog_args,
        custom_args_text=profile.custom_args_text,
        labels=json.loads(profile.labels_json),
    )


def _build_argv_with_flags(
    settings: AppSettings,
    config: LaunchConfig,
    known: set[str],
    canonical: dict[str, str],
):
    if config.mode == "single":
        launch_args = ["--model", config.model_path, "--alias", config.model_alias]
    else:
        launch_args = ["--models-dir", config.models_dir]
        if config.models_preset:
            launch_args.extend(["--models-preset", config.models_preset])
        launch_args.extend(["--models-max", str(config.models_max)])
        if config.models_autoload:
            launch_args.append("--models-autoload")
    return build_server_argv(
        settings,
        launch_args,
        config.catalog_args,
        config.custom_args_text,
        known,
        canonical,
    )


def build_launch_argv(db: Session, settings: AppSettings, config: LaunchConfig):
    return _build_argv_with_flags(settings, config, known_flags(db), canonical_flags(db))


def _apply_config(profile: Profile, payload: ProfileCreate, config: LaunchConfig) -> None:
    profile.name = payload.name
    profile.mode = config.mode
    profile.model_path = config.model_path
    profile.model_alias = config.model_alias
    profile.models_dir = config.models_dir
    profile.models_preset = config.models_preset
    profile.models_max = config.models_max
    profile.models_autoload = config.models_autoload
    profile.catalog_args_json = json.dumps([item.model_dump() for item in config.catalog_args], ensure_ascii=False)
    profile.custom_args_text = config.custom_args_text
    profile.labels_json = json.dumps(config.labels, ensure_ascii=False)
    profile.service_id = None
    profile.is_active = False
    profile.models.clear()
    for item in config.models:
        profile.models.append(ProfileModel(id=str(uuid.uuid4()), **item.model_dump()))


def _save_version(db: Session, settings: AppSettings, profile: Profile) -> ProfileVersion:
    config = launch_config_from_profile(profile)
    built = build_launch_argv(db, settings, config)
    version = ProfileVersion(
        id=str(uuid.uuid4()),
        profile_id=profile.id,
        spec_json=json.dumps({"name": profile.name, **config.model_dump(mode="json")}, ensure_ascii=False),
        argv_json=json.dumps(built.argv, ensure_ascii=False),
    )
    db.add(version)
    return version


def create_profile(db: Session, settings: AppSettings, payload: ProfileCreate) -> Profile:
    config = normalize_launch_config(settings, LaunchConfig.model_validate(payload.model_dump()))
    profile = Profile(id=str(uuid.uuid4()), name=payload.name, model_path="")
    _apply_config(profile, payload, config)
    db.add(profile)
    db.flush()
    _save_version(db, settings, profile)
    db.commit()
    db.refresh(profile)
    return profile


def update_profile(db: Session, settings: AppSettings, profile: Profile, payload: ProfileCreate) -> Profile:
    config = normalize_launch_config(settings, LaunchConfig.model_validate(payload.model_dump()))
    _apply_config(profile, payload, config)
    db.flush()
    _save_version(db, settings, profile)
    db.commit()
    db.refresh(profile)
    return profile


def serialize_profile(
    db: Session,
    settings: AppSettings,
    profile: Profile,
    flags: tuple[set[str], dict[str, str]] | None = None,
) -> ProfileOut:
    config = launch_config_from_profile(profile)
    if flags is not None:
        known, canonical = flags
    else:
        known, canonical = known_flags(db), canonical_flags(db)
    built = _build_argv_with_flags(settings, config, known, canonical)
    return ProfileOut(
        id=profile.id,
        name=profile.name,
        **config.model_dump(),
        final_argv=built.argv,
        warnings=built.warnings,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )
