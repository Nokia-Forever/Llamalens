from __future__ import annotations

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select, update

from app.database import SessionLocal
from app.models import LlamaService, Profile, SwitchJob
from app.services.job_control import EXECUTION_LOCK
from app.services.llama_services import (
    app_settings_for_service,
    deploy_unit_content,
    payload_for_service,
    render_unit,
)
from app.services.profiles_service import atomic_write_text, serialize_profile, write_active_profile
from app.services.settings_service import get_settings
from app.services.systemd import probe_binary, read_journal, run_service_action, run_unit_action


SWITCH_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="llamalens-switch")


def create_switch_job(profile_id: str) -> SwitchJob:
    db = SessionLocal()
    try:
        job = SwitchJob(id=str(uuid.uuid4()), profile_id=profile_id, status="queued", message="等待切换")
        db.add(job)
        db.commit()
        db.refresh(job)
        SWITCH_EXECUTOR.submit(_run_switch, job.id)
        return job
    finally:
        db.close()


def _active_profile_query(profile: Profile):
    statement = select(Profile).where(Profile.is_active.is_(True))
    if profile.service_id is None:
        return statement.where(Profile.service_id.is_(None))
    return statement.where(Profile.service_id == profile.service_id)


def _clear_active_profiles(db, profile: Profile) -> None:
    if profile.service_id is None:
        db.execute(update(Profile).where(Profile.service_id.is_(None)).values(is_active=False))
    else:
        db.execute(update(Profile).where(Profile.service_id == profile.service_id).values(is_active=False))


def _run_switch(job_id: str) -> None:
    with EXECUTION_LOCK:
        db = SessionLocal()
        previous_content: str | None = None
        previous_unit_content: str | None = None
        previous_profile_id: str | None = None
        active_path: Path | None = None
        service: LlamaService | None = None
        profile: Profile | None = None
        try:
            job = db.get(SwitchJob, job_id)
            if job is None:
                return
            profile = db.get(Profile, job.profile_id)
            if profile is None:
                raise ValueError("Profile 不存在")
            settings = get_settings(db)
            service = db.get(LlamaService, profile.service_id) if profile.service_id else None
            if service is not None:
                if service.archived_at is not None:
                    raise ValueError("目标服务已归档")
                settings = app_settings_for_service(service, settings)
                previous_unit_content = service.rendered_unit

            previous_active = db.scalar(_active_profile_query(profile))
            previous_profile_id = previous_active.id if previous_active else None
            active_path = Path(settings.active_profile_path).expanduser()
            if active_path.exists():
                previous_content = active_path.read_text(encoding="utf-8")
            job.status = "activating"
            job.message = "写入活动 Profile 并重启服务"
            db.commit()

            probe = probe_binary(settings)
            version = str(probe.get("version") or "") or None
            version_row = write_active_profile(db, settings, profile, version)
            if service is not None:
                serialized = serialize_profile(db, settings, profile)
                rendered = render_unit(
                    payload_for_service(service),
                    service.unit_name,
                    argv_override=serialized.final_argv,
                )
                service.rendered_unit = str(rendered["content"])
                service.model_path = profile.model_path
                if profile.model_alias:
                    service.model_alias = profile.model_alias
                db.commit()
                restart_details = deploy_unit_content(service, service.rendered_unit, enable_now=False)
                restart_ok = bool(restart_details.get("ok"))
            else:
                restart = run_service_action(settings, "restart", timeout=60)
                restart_details = restart.__dict__
                restart_ok = restart.ok
            if not restart_ok:
                raise RuntimeError(f"systemctl restart 失败: {restart_details}")

            deadline = time.monotonic() + 600
            health_url = f"http://{settings.llama_host}:{settings.llama_port}{settings.health_path}"
            health_error = ""
            while time.monotonic() < deadline:
                try:
                    response = httpx.get(health_url, timeout=3)
                    if 200 <= response.status_code < 300:
                        job.status = "succeeded"
                        job.message = "服务健康，Profile 已激活"
                        job.finished_at = datetime.now(timezone.utc)
                        job.diagnostics_json = json.dumps(
                            {
                                "profile_version_id": version_row.id,
                                "restart": restart_details,
                                "health": response.status_code,
                            },
                            ensure_ascii=False,
                        )
                        db.commit()
                        return
                    health_error = f"HTTP {response.status_code}"
                except Exception as exc:
                    health_error = str(exc)
                time.sleep(1)
            raise TimeoutError(f"服务健康检查超时: {health_error}")
        except Exception as exc:
            rollback: dict[str, object] = {"attempted": False}
            try:
                if service is not None and previous_unit_content is not None:
                    service.rendered_unit = previous_unit_content
                    db.commit()
                    rollback = {
                        "attempted": True,
                        "result": deploy_unit_content(service, previous_unit_content, enable_now=False),
                    }
                elif active_path is not None and previous_content is not None:
                    atomic_write_text(active_path, previous_content)
                    settings = get_settings(db)
                    rollback_result = run_service_action(settings, "restart", timeout=60)
                    rollback = {"attempted": True, "result": rollback_result.__dict__}
                elif active_path is not None and active_path.exists():
                    active_path.unlink()
                    rollback = {"attempted": True, "result": "candidate active profile removed"}
                if profile is not None:
                    _clear_active_profiles(db, profile)
                if previous_profile_id is not None:
                    previous = db.get(Profile, previous_profile_id)
                    if previous is not None:
                        previous.is_active = True
                db.commit()
            except Exception as rollback_exc:
                rollback = {"attempted": True, "error": str(rollback_exc)}
            job = db.get(SwitchJob, job_id)
            if job is not None:
                job.status = "failed"
                job.message = f"切换失败: {exc}"
                try:
                    if service is not None:
                        journal = run_unit_action(service.unit_name, "status")
                    else:
                        journal = read_journal(get_settings(db), 100)
                    diagnostics = {"error": str(exc), "rollback": rollback, "journal": journal.__dict__}
                except Exception:
                    diagnostics = {"error": str(exc), "rollback": rollback}
                job.diagnostics_json = json.dumps(diagnostics, ensure_ascii=False)
                job.finished_at = datetime.now(timezone.utc)
                db.commit()
        finally:
            db.close()
