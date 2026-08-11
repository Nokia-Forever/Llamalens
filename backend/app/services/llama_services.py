from __future__ import annotations

import json
import os
import re
import shlex
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import LlamaService, Profile, ProfileModel
from app.schemas import AppSettings, LaunchConfig, LlamaServiceCreate
from app.services.profiles_service import build_launch_argv, launch_config_from_profile, normalize_launch_config
from app.services.systemd import daemon_reload, read_unit_journal, run_unit_action


MANAGED_UNIT_PATTERN = re.compile(r"llamalens-[A-Za-z0-9_.@-]+\.service")


def systemd_directory() -> Path:
    return Path(os.getenv("LLAMALENS_SYSTEMD_DIR", "/etc/systemd/system")).resolve(strict=False)


def archive_directory() -> Path:
    data_dir = Path(os.getenv("LLAMALENS_DATA_DIR", "/var/lib/llama-lens"))
    return (data_dir / "archive" / "services").resolve(strict=False)


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.@-]+", "-", value.strip()).strip("-.").lower()
    return slug or "service"


def normalize_unit_name(name: str, requested: str = "") -> str:
    unit_name = requested.strip() or f"llamalens-{_slug(name)}.service"
    if not unit_name.endswith(".service"):
        unit_name += ".service"
    if not unit_name.startswith("llamalens-"):
        unit_name = f"llamalens-{unit_name}"
    if not MANAGED_UNIT_PATTERN.fullmatch(unit_name):
        raise ValueError("unit 名称只能使用字母、数字、点、下划线、@ 和短横线")
    return unit_name


def unit_path_for(unit_name: str) -> Path:
    if not MANAGED_UNIT_PATTERN.fullmatch(unit_name):
        raise ValueError("拒绝管理非 LlamaLens unit")
    root = systemd_directory()
    path = (root / unit_name).resolve(strict=False)
    path.relative_to(root)
    return path


def _extra_lines(section: str, text: str) -> list[str]:
    if "\x00" in text:
        raise ValueError(f"[{section}] 自定义内容不能包含 NUL")
    managed_service_keys = {"ExecStart", "Type", "Restart", "RestartSec"}
    result: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            raise ValueError(f"[{section}] 自定义内容不能创建新的 section")
        if re.match(r"(?i)^ExecStart\s*=", line):
            raise ValueError("ExecStart 由 LlamaLens 生成，不能在自定义内容中重复设置")
        if section == "Service":
            match = re.match(r"(?i)^([A-Za-z][A-Za-z0-9-]*)\s*=", line)
            if match and match.group(1) in managed_service_keys:
                raise ValueError(f"{match.group(1)} 由 LlamaLens 生成，不能在 [Service] 自定义内容中重复设置")
        if "=" not in line and not line.startswith(("#", ";")):
            raise ValueError(f"[{section}] 自定义行必须是 systemd 指令: {line}")
        result.append(line)
    return result


def _decode_launch(value: str) -> LaunchConfig | None:
    if not value:
        return None
    return LaunchConfig.model_validate_json(value)


def launch_aliases(config: LaunchConfig | None) -> list[str]:
    if config is None:
        return []
    if config.mode == "single":
        return [config.model_alias]
    return [item.alias for item in config.models if item.enabled]


def app_settings_for_service(row: LlamaService, base: AppSettings | None = None) -> AppSettings:
    settings = base.model_copy(deep=True) if base is not None else AppSettings()
    settings.llama_server_bin = row.server_bin
    settings.llama_service_name = row.unit_name
    settings.llama_service_file = row.unit_path
    settings.service_scope = "system"
    settings.service_control_command = "systemctl"
    settings.llama_host = row.host
    settings.llama_port = row.port
    settings.health_path = row.health_path
    settings.request_path = row.request_path
    settings.active_profile_path = str(Path(os.getenv("LLAMALENS_DATA_DIR", "/var/lib/llama-lens")) / "services" / row.id / "active-profile.json")
    return settings


def render_unit(payload: LlamaServiceCreate, argv: list[str], unit_name: str | None = None) -> dict[str, object]:
    normalized_name = normalize_unit_name(payload.name, unit_name if unit_name is not None else payload.unit_name)
    lines = [
        "[Unit]",
        f"Description={payload.description.strip() or payload.name}",
        "Wants=network-online.target",
        "After=network-online.target",
        *_extra_lines("Unit", payload.unit_extra_text),
        "",
        "[Service]",
        f"Type={payload.service_type}",
        f"User={payload.service_user.strip() or 'root'}",
        f"Group={payload.service_group.strip() or payload.service_user.strip() or 'root'}",
        f"WorkingDirectory={payload.working_directory.strip() or '/'}",
        f"ExecStart={shlex.join(argv)}",
        f"Restart={payload.restart_policy}",
        f"RestartSec={payload.restart_sec}",
        *_extra_lines("Service", payload.service_extra_text),
        "",
        "[Install]",
        "WantedBy=multi-user.target",
        *_extra_lines("Install", payload.install_extra_text),
        "",
    ]
    return {"unit_name": normalized_name, "unit_path": str(unit_path_for(normalized_name)), "argv": argv, "content": "\n".join(lines)}


def payload_for_service(row: LlamaService) -> LlamaServiceCreate:
    return LlamaServiceCreate(
        name=row.name, description=row.description, unit_name=row.unit_name, server_bin=row.server_bin,
        service_user=row.service_user, service_group=row.service_group, working_directory=row.working_directory,
        host=row.host, port=row.port, health_path=row.health_path, request_path=row.request_path,
        service_type=row.service_type, restart_policy=row.restart_policy, restart_sec=row.restart_sec,
        unit_extra_text=row.unit_extra_text, service_extra_text=row.service_extra_text,
        install_extra_text=row.install_extra_text,
    )


def preview_service(db: Session, row: LlamaService, settings: AppSettings) -> dict[str, object]:
    config = _decode_launch(row.draft_launch_config_json)
    if config is None:
        raise ValueError("请先从 Profile 导入启动配置")
    built = build_launch_argv(db, app_settings_for_service(row, settings), config)
    rendered = render_unit(payload_for_service(row), built.argv, row.unit_name)
    rendered["warnings"] = built.warnings
    rendered["launch_config"] = config.model_dump(mode="json")
    return rendered


def _atomic_write(path: Path, content: str) -> None:
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


def _assign(row: LlamaService, payload: LlamaServiceCreate, unit_name: str) -> None:
    row.name = payload.name
    row.description = payload.description
    row.unit_name = unit_name
    row.unit_path = str(unit_path_for(unit_name))
    row.server_bin = payload.server_bin
    row.service_user = payload.service_user
    row.service_group = payload.service_group
    row.working_directory = payload.working_directory
    row.host = payload.host
    row.port = payload.port
    row.health_path = payload.health_path
    row.request_path = payload.request_path
    row.service_type = payload.service_type
    row.restart_policy = payload.restart_policy
    row.restart_sec = payload.restart_sec
    row.unit_extra_text = payload.unit_extra_text
    row.service_extra_text = payload.service_extra_text
    row.install_extra_text = payload.install_extra_text


def serialize_service(row: LlamaService, status: bool = False) -> dict[str, object]:
    draft = _decode_launch(row.draft_launch_config_json)
    applied = _decode_launch(row.applied_launch_config_json)
    current_service_config = payload_for_service(row).model_dump(mode="json")
    applied_service_config = json.loads(row.applied_service_config_json) if row.applied_service_config_json else None
    result: dict[str, object] = {
        "id": row.id, "name": row.name, "description": row.description, "unit_name": row.unit_name,
        "unit_path": row.unit_path, "server_bin": row.server_bin, "service_user": row.service_user,
        "service_group": row.service_group, "working_directory": row.working_directory, "host": row.host,
        "port": row.port, "health_path": row.health_path, "request_path": row.request_path,
        "service_type": row.service_type, "restart_policy": row.restart_policy, "restart_sec": row.restart_sec,
        "unit_extra_text": row.unit_extra_text, "service_extra_text": row.service_extra_text,
        "install_extra_text": row.install_extra_text, "rendered_unit": row.rendered_unit,
        "source_profile_id": row.source_profile_id,
        "applied_source_profile_id": row.applied_source_profile_id,
        "draft_launch_config": draft.model_dump(mode="json") if draft else None,
        "applied_launch_config": applied.model_dump(mode="json") if applied else None,
        "applied_service_config": applied_service_config,
        "applied_model_aliases": launch_aliases(applied),
        "has_pending_changes": (
            row.draft_launch_config_json != row.applied_launch_config_json
            or (applied is not None and current_service_config != applied_service_config)
        ),
        "archived_at": row.archived_at, "created_at": row.created_at, "updated_at": row.updated_at,
    }
    if status:
        result["status"] = run_unit_action(row.unit_name, "status").__dict__
    return result


def create_service(db: Session, payload: LlamaServiceCreate) -> LlamaService:
    unit_name = normalize_unit_name(payload.name, payload.unit_name)
    if db.scalar(select(LlamaService.id).where(LlamaService.unit_name == unit_name).limit(1)):
        raise ValueError("unit 名称已经存在")
    if db.scalar(select(LlamaService.id).where(LlamaService.host == payload.host, LlamaService.port == payload.port, LlamaService.archived_at.is_(None)).limit(1)):
        raise ValueError("该 host/port 已被另一个服务使用")
    row = LlamaService(id=str(uuid.uuid4()))
    _assign(row, payload, unit_name)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_service(db: Session, row: LlamaService, payload: LlamaServiceCreate) -> LlamaService:
    if payload.unit_name and normalize_unit_name(payload.name, payload.unit_name) != row.unit_name:
        raise ValueError("unit 名称创建后不可修改")
    conflict = db.scalar(select(LlamaService.id).where(LlamaService.id != row.id, LlamaService.host == payload.host, LlamaService.port == payload.port, LlamaService.archived_at.is_(None)).limit(1))
    if conflict:
        raise ValueError("该 host/port 已被另一个服务使用")
    _assign(row, payload, row.unit_name)
    db.commit()
    db.refresh(row)
    return row


def select_profile(db: Session, row: LlamaService, profile: Profile) -> LlamaService:
    config = launch_config_from_profile(profile)
    row.source_profile_id = profile.id
    row.draft_launch_config_json = config.model_dump_json()
    db.commit()
    db.refresh(row)
    return row


def update_launch_config(db: Session, row: LlamaService, settings: AppSettings, payload: LaunchConfig) -> LlamaService:
    config = normalize_launch_config(settings, payload)
    row.draft_launch_config_json = config.model_dump_json()
    db.commit()
    db.refresh(row)
    return row


def deploy_service(db: Session, row: LlamaService, settings: AppSettings) -> dict[str, object]:
    rendered = preview_service(db, row, settings)
    path = unit_path_for(row.unit_name)
    _atomic_write(path, str(rendered["content"]))
    reload_result = daemon_reload()
    if not reload_result.ok:
        return {"ok": False, "reload": reload_result.__dict__}
    action_result = run_unit_action(row.unit_name, "enable-now", timeout=120)
    status_result = run_unit_action(row.unit_name, "status")
    ok = reload_result.ok and action_result.ok
    if ok:
        row.rendered_unit = str(rendered["content"])
        row.applied_launch_config_json = row.draft_launch_config_json
        row.applied_service_config_json = payload_for_service(row).model_dump_json()
        row.applied_source_profile_id = row.source_profile_id
        db.commit()
    return {"ok": ok, "reload": reload_result.__dict__, "action": action_result.__dict__, "status": status_result.__dict__}


def archive_service(db: Session, row: LlamaService) -> dict[str, object]:
    stop = run_unit_action(row.unit_name, "stop", timeout=120)
    disable = run_unit_action(row.unit_name, "disable")
    path = unit_path_for(row.unit_name)
    archived_path = archive_directory() / row.id / row.unit_name
    if path.exists():
        archived_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(path, archived_path)
    reload_result = daemon_reload()
    row.archived_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": stop.ok and disable.ok and reload_result.ok, "stop": stop.__dict__, "disable": disable.__dict__, "reload": reload_result.__dict__, "archive_path": str(archived_path)}


def restore_service(db: Session, row: LlamaService) -> dict[str, object]:
    archived_path = archive_directory() / row.id / row.unit_name
    path = unit_path_for(row.unit_name)
    if archived_path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(archived_path, path)
    elif row.rendered_unit:
        _atomic_write(path, row.rendered_unit)
    reload_result = daemon_reload()
    row.archived_at = None
    db.commit()
    return {"ok": reload_result.ok, "reload": reload_result.__dict__, "unit_path": str(path)}


def delete_service(db: Session, row: LlamaService) -> dict[str, object]:
    stop = run_unit_action(row.unit_name, "stop", timeout=120)
    disable = run_unit_action(row.unit_name, "disable")
    path = unit_path_for(row.unit_name)
    if path.exists():
        path.unlink()
    archived_path = archive_directory() / row.id / row.unit_name
    if archived_path.exists():
        archived_path.unlink()
    reload_result = daemon_reload()
    db.delete(row)
    db.commit()
    return {"ok": stop.ok and disable.ok and reload_result.ok, "stop": stop.__dict__, "disable": disable.__dict__, "reload": reload_result.__dict__}


def service_logs(row: LlamaService, lines: int) -> dict[str, object]:
    return read_unit_journal(row.unit_name, lines).__dict__


def _legacy_launch_config(service: LlamaService) -> LaunchConfig | None:
    if service.mode == "router" and service.models_dir:
        return LaunchConfig(
            mode="router", models_dir=service.models_dir, models_preset=service.models_preset,
            models_max=service.models_max, models_autoload=service.models_autoload,
            models=[{"alias": item.alias, "model_path": item.model_path, "display_name": item.display_name, "enabled": item.enabled} for item in service.models],
            custom_args_text=service.custom_args_text,
        )
    if service.model_path and service.model_alias:
        return LaunchConfig(mode="single", model_path=service.model_path, model_alias=service.model_alias, custom_args_text=service.custom_args_text)
    return None


def _create_migrated_profile(db: Session, service: LlamaService, config: LaunchConfig) -> Profile:
    profile = Profile(
        id=str(uuid.uuid4()), name=f"{service.name} migrated profile", service_id=None, is_active=False,
        mode=config.mode, model_path=config.model_path, model_alias=config.model_alias,
        models_dir=config.models_dir, models_preset=config.models_preset,
        models_max=config.models_max, models_autoload=config.models_autoload,
        catalog_args_json=json.dumps([item.model_dump() for item in config.catalog_args], ensure_ascii=False),
        custom_args_text=config.custom_args_text, labels_json=json.dumps(config.labels, ensure_ascii=False),
    )
    for item in config.models:
        profile.models.append(ProfileModel(id=str(uuid.uuid4()), **item.model_dump()))
    db.add(profile)
    db.flush()
    return profile


def migrate_legacy_service(db: Session, settings: AppSettings) -> LlamaService | None:
    services = db.scalars(select(LlamaService)).all()
    if not services:
        profile = db.scalar(select(Profile).order_by(Profile.is_active.desc(), Profile.created_at.asc()).limit(1))
        if profile is None:
            return None
        row = LlamaService(id=str(uuid.uuid4()))
        payload = LlamaServiceCreate(
            name="Legacy llama.cpp service", description="Migrated from LlamaLens V1 settings",
            unit_name="llamalens-legacy.service", server_bin=settings.llama_server_bin,
            working_directory=str(Path(settings.llama_server_bin).parent), host=settings.llama_host,
            port=settings.llama_port, health_path=settings.health_path, request_path=settings.request_path,
        )
        _assign(row, payload, payload.unit_name)
        db.add(row)
        db.flush()
        services = [row]

    for service in services:
        if service.draft_launch_config_json:
            if service.applied_launch_config_json and not service.applied_service_config_json:
                service.applied_service_config_json = payload_for_service(service).model_dump_json()
            if service.applied_launch_config_json and not service.applied_source_profile_id:
                service.applied_source_profile_id = service.source_profile_id
            continue
        profile = db.scalar(
            select(Profile)
            .where(Profile.service_id == service.id)
            .order_by(Profile.is_active.desc(), Profile.updated_at.desc())
            .limit(1)
        )
        if profile is not None:
            config = launch_config_from_profile(profile)
        else:
            config = _legacy_launch_config(service)
            if config is None:
                continue
            profile = _create_migrated_profile(db, service, config)
        service.source_profile_id = profile.id
        service.draft_launch_config_json = config.model_dump_json()
        if Path(service.unit_path).is_file() and service.rendered_unit:
            service.applied_launch_config_json = service.draft_launch_config_json
            service.applied_service_config_json = payload_for_service(service).model_dump_json()
            service.applied_source_profile_id = service.source_profile_id

    db.execute(update(Profile).values(service_id=None, is_active=False))
    db.commit()
    return services[0] if services else None
