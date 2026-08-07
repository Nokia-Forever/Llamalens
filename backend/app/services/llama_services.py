from __future__ import annotations

import os
import re
import shlex
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LlamaService, Profile, ServiceModel
from app.schemas import AppSettings, LlamaServiceCreate
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
    result: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            raise ValueError(f"[{section}] 自定义内容不能创建新的 section")
        if re.match(r"(?i)^ExecStart\s*=", line):
            raise ValueError("ExecStart 由 LlamaLens 生成，不能在自定义内容中重复设置")
        if "=" not in line and not line.startswith(("#", ";")):
            raise ValueError(f"[{section}] 自定义行必须是 systemd 指令: {line}")
        result.append(line)
    return result


def build_argv(payload: LlamaServiceCreate) -> list[str]:
    if "\x00" in payload.custom_args_text:
        raise ValueError("llama-server 自定义参数不能包含 NUL")
    argv = [payload.server_bin]
    if payload.mode == "single":
        if not payload.model_path.strip():
            raise ValueError("单模型服务必须设置模型路径")
        if not payload.model_alias.strip():
            raise ValueError("单模型服务必须设置模型 alias")
        argv.extend(["--model", payload.model_path, "--alias", payload.model_alias])
    else:
        if not payload.models_dir.strip():
            raise ValueError("Router 服务必须设置 models directory")
        enabled_models = [model for model in payload.models if model.enabled]
        if not enabled_models:
            raise ValueError("Router 服务至少需要一个可选模型 alias")
        aliases = [model.alias for model in enabled_models]
        if len(aliases) != len(set(aliases)):
            raise ValueError("同一服务中的模型 alias 不能重复")
        argv.extend(["--models-dir", payload.models_dir])
        if payload.models_preset.strip():
            argv.extend(["--models-preset", payload.models_preset])
        argv.extend(["--models-max", str(payload.models_max)])
        if payload.models_autoload:
            argv.append("--models-autoload")
    argv.extend(["--host", payload.host, "--port", str(payload.port)])
    if payload.custom_args_text.strip():
        argv.extend(shlex.split(payload.custom_args_text, posix=True))
    return argv


def render_unit(
    payload: LlamaServiceCreate,
    unit_name: str | None = None,
    argv_override: list[str] | None = None,
) -> dict[str, object]:
    normalized_name = normalize_unit_name(payload.name, unit_name if unit_name is not None else payload.unit_name)
    argv = argv_override or build_argv(payload)
    unit_lines = [
        "[Unit]",
        f"Description={payload.description.strip() or payload.name}",
        "Wants=network-online.target",
        "After=network-online.target",
        *_extra_lines("Unit", payload.unit_extra_text),
        "",
        "[Service]",
        "Type=exec",
        f"User={payload.service_user.strip() or 'root'}",
        f"Group={payload.service_group.strip() or payload.service_user.strip() or 'root'}",
        f"WorkingDirectory={payload.working_directory.strip() or '/'}",
        f"ExecStart={shlex.join(argv)}",
        "Restart=on-failure",
        "RestartSec=3",
        *_extra_lines("Service", payload.service_extra_text),
        "",
        "[Install]",
        "WantedBy=multi-user.target",
        *_extra_lines("Install", payload.install_extra_text),
        "",
    ]
    return {"unit_name": normalized_name, "unit_path": str(unit_path_for(normalized_name)), "argv": argv, "content": "\n".join(unit_lines)}


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


def _assign(row: LlamaService, payload: LlamaServiceCreate, rendered: dict[str, object]) -> None:
    row.name = payload.name
    row.description = payload.description
    row.unit_name = str(rendered["unit_name"])
    row.unit_path = str(rendered["unit_path"])
    row.server_bin = payload.server_bin
    row.service_user = payload.service_user
    row.service_group = payload.service_group
    row.working_directory = payload.working_directory
    row.host = payload.host
    row.port = payload.port
    row.health_path = payload.health_path
    row.request_path = payload.request_path
    row.mode = payload.mode
    row.model_path = payload.model_path
    row.model_alias = payload.model_alias
    row.models_dir = payload.models_dir
    row.models_preset = payload.models_preset
    row.models_max = payload.models_max
    row.models_autoload = payload.models_autoload
    row.custom_args_text = payload.custom_args_text
    row.unit_extra_text = payload.unit_extra_text
    row.service_extra_text = payload.service_extra_text
    row.install_extra_text = payload.install_extra_text
    row.rendered_unit = str(rendered["content"])


def _replace_models(row: LlamaService, payload: LlamaServiceCreate) -> None:
    row.models.clear()
    if payload.mode == "single":
        row.models.append(ServiceModel(id=str(uuid.uuid4()), alias=payload.model_alias, model_path=payload.model_path, display_name=payload.model_alias))
    else:
        for item in payload.models:
            row.models.append(ServiceModel(id=str(uuid.uuid4()), **item.model_dump()))


def serialize_service(row: LlamaService, status: bool = False) -> dict[str, object]:
    result: dict[str, object] = {
        "id": row.id, "name": row.name, "description": row.description, "unit_name": row.unit_name,
        "unit_path": row.unit_path, "server_bin": row.server_bin, "service_user": row.service_user,
        "service_group": row.service_group, "working_directory": row.working_directory, "host": row.host,
        "port": row.port, "health_path": row.health_path, "request_path": row.request_path, "mode": row.mode,
        "model_path": row.model_path, "model_alias": row.model_alias, "models_dir": row.models_dir,
        "models_preset": row.models_preset, "models_max": row.models_max, "models_autoload": row.models_autoload,
        "custom_args_text": row.custom_args_text, "unit_extra_text": row.unit_extra_text,
        "service_extra_text": row.service_extra_text, "install_extra_text": row.install_extra_text,
        "rendered_unit": row.rendered_unit, "archived_at": row.archived_at, "created_at": row.created_at,
        "updated_at": row.updated_at,
        "models": [{"id": item.id, "alias": item.alias, "model_path": item.model_path, "display_name": item.display_name, "enabled": item.enabled} for item in row.models],
    }
    if status:
        result["status"] = run_unit_action(row.unit_name, "status").__dict__
    return result


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
    settings.active_profile_path = str(
        Path(os.getenv("LLAMALENS_DATA_DIR", "/var/lib/llama-lens"))
        / "services"
        / row.id
        / "active-profile.json"
    )
    return settings


def payload_for_service(row: LlamaService) -> LlamaServiceCreate:
    return LlamaServiceCreate.model_validate(serialize_service(row))


def create_service(db: Session, payload: LlamaServiceCreate) -> LlamaService:
    unit_name = normalize_unit_name(payload.name, payload.unit_name)
    if db.scalar(select(LlamaService.id).where(LlamaService.unit_name == unit_name).limit(1)):
        raise ValueError("unit 名称已经存在")
    if db.scalar(select(LlamaService.id).where(LlamaService.host == payload.host, LlamaService.port == payload.port, LlamaService.archived_at.is_(None)).limit(1)):
        raise ValueError("该 host/port 已被另一个服务使用")
    rendered = render_unit(payload, unit_name)
    row = LlamaService(id=str(uuid.uuid4()))
    _assign(row, payload, rendered)
    _replace_models(row, payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def migrate_legacy_service(db: Session, settings: AppSettings) -> LlamaService | None:
    """Create one managed service for V1 databases that already contain Profiles."""
    if db.scalar(select(LlamaService.id).limit(1)) is not None:
        return None
    profile = db.scalar(select(Profile).order_by(Profile.is_active.desc(), Profile.created_at.asc()).limit(1))
    if profile is None:
        return None
    alias = (profile.model_alias or _slug(profile.name)).replace(" ", "-")
    payload = LlamaServiceCreate(
        name="Legacy llama.cpp service",
        description="Migrated from LlamaLens V1 settings",
        unit_name="llamalens-legacy.service",
        server_bin=settings.llama_server_bin,
        working_directory=str(Path(settings.llama_server_bin).parent),
        host=settings.llama_host,
        port=settings.llama_port,
        health_path=settings.health_path,
        request_path=settings.request_path,
        mode="single",
        model_path=profile.model_path,
        model_alias=alias,
        custom_args_text=profile.custom_args_text,
    )
    row = create_service(db, payload)
    for existing in db.scalars(select(Profile).where(Profile.service_id.is_(None))).all():
        existing.service_id = row.id
        if not existing.model_alias:
            existing.model_alias = alias
    db.commit()
    return row


def update_service(db: Session, row: LlamaService, payload: LlamaServiceCreate) -> LlamaService:
    if payload.unit_name and normalize_unit_name(payload.name, payload.unit_name) != row.unit_name:
        raise ValueError("unit 名称创建后不可修改")
    conflict = db.scalar(select(LlamaService.id).where(LlamaService.id != row.id, LlamaService.host == payload.host, LlamaService.port == payload.port, LlamaService.archived_at.is_(None)).limit(1))
    if conflict:
        raise ValueError("该 host/port 已被另一个服务使用")
    rendered = render_unit(payload, row.unit_name)
    _assign(row, payload, rendered)
    _replace_models(row, payload)
    db.commit()
    db.refresh(row)
    return row


def deploy_service(row: LlamaService) -> dict[str, object]:
    rendered = render_unit(payload_for_service(row), row.unit_name)
    return deploy_unit_content(row, str(rendered["content"]), enable_now=True)


def deploy_unit_content(row: LlamaService, content: str, enable_now: bool = False) -> dict[str, object]:
    path = unit_path_for(row.unit_name)
    _atomic_write(path, content)
    reload_result = daemon_reload()
    if not reload_result.ok:
        return {"ok": False, "reload": reload_result.__dict__}
    action_result = run_unit_action(row.unit_name, "enable-now" if enable_now else "restart", timeout=120)
    status_result = run_unit_action(row.unit_name, "status")
    return {
        "ok": reload_result.ok and action_result.ok,
        "reload": reload_result.__dict__,
        "action": action_result.__dict__,
        "status": status_result.__dict__,
    }


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
    else:
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
    db.execute(Profile.__table__.update().where(Profile.service_id == row.id).values(service_id=None))
    db.delete(row)
    db.commit()
    return {"ok": stop.ok and disable.ok and reload_result.ok, "stop": stop.__dict__, "disable": disable.__dict__, "reload": reload_result.__dict__}


def service_logs(row: LlamaService, lines: int) -> dict[str, object]:
    return read_unit_journal(row.unit_name, lines).__dict__
