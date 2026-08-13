from __future__ import annotations

import json
import platform
import shlex
import subprocess
from dataclasses import dataclass

from app.logging_config import get_logger
from app.schemas import AppSettings


logger = get_logger(__name__)


def _log_result(event: str, result: "CommandResult") -> None:
    logger.info(
        event,
        extra={
            "argv": result.argv,
            "returncode": result.returncode,
            "ok": result.ok,
            "stderr": (result.stderr or "")[:300],
        },
    )


@dataclass
class CommandResult:
    ok: bool
    argv: list[str]
    returncode: int | None
    stdout: str
    stderr: str


def _prefix(settings: AppSettings) -> list[str]:
    if settings.service_scope == "user":
        return ["systemctl", "--user"]
    prefix = shlex.split(settings.service_control_command, posix=True)
    allowed = [
        ["systemctl"],
        ["/usr/bin/systemctl"],
        ["sudo", "-n", "systemctl"],
        ["/usr/bin/sudo", "-n", "/usr/bin/systemctl"],
    ]
    if prefix not in allowed:
        raise ValueError("系统级服务控制命令不在允许列表中")
    return prefix


def run_service_action(settings: AppSettings, action: str, timeout: int = 30) -> CommandResult:
    if action not in {"start", "stop", "restart", "status"}:
        raise ValueError("不支持的 service 操作")
    argv = [*_prefix(settings), action, settings.llama_service_name]
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
        result = CommandResult(completed.returncode == 0, argv, completed.returncode, completed.stdout, completed.stderr)
    except (OSError, subprocess.TimeoutExpired) as exc:
        result = CommandResult(False, argv, None, "", f"{type(exc).__name__}: {exc}")
    _log_result("systemctl.service_action", result)
    return result


def run_unit_action(unit_name: str, action: str, timeout: int = 30) -> CommandResult:
    if action not in {"start", "stop", "restart", "status", "enable", "disable", "enable-now"}:
        raise ValueError("不支持的 service 操作")
    if action == "enable-now":
        argv = ["systemctl", "enable", "--now", unit_name]
    else:
        argv = ["systemctl", action, unit_name]
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
        result = CommandResult(completed.returncode == 0, argv, completed.returncode, completed.stdout, completed.stderr)
    except (OSError, subprocess.TimeoutExpired) as exc:
        result = CommandResult(False, argv, None, "", f"{type(exc).__name__}: {exc}")
    _log_result("systemctl.unit_action", result)
    return result


def list_units_status(pattern: str, timeout: int = 30) -> dict[str, CommandResult]:
    argv = ["systemctl", "list-units", pattern, "--output=json", "--all", "--no-pager"]
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
        result = CommandResult(completed.returncode == 0, argv, completed.returncode, completed.stdout, completed.stderr)
    except (OSError, subprocess.TimeoutExpired) as exc:
        result = CommandResult(False, argv, None, "", f"{type(exc).__name__}: {exc}")
    _log_result("systemctl.list_units", result)
    if not result.ok or not result.stdout:
        return {}
    try:
        units = json.loads(result.stdout)
    except (ValueError, TypeError):
        logger.warning("systemctl.list_units_parse_failed", extra={"stderr": (result.stderr or "")[:300]})
        return {}
    status_map: dict[str, CommandResult] = {}
    for unit in units:
        if not isinstance(unit, dict):
            continue
        name = unit.get("unit")
        if not name:
            continue
        active = unit.get("active", "unknown")
        sub = unit.get("sub", "")
        description = unit.get("description", "")
        ok = active == "active"
        stdout_text = f"{active} ({sub})" if sub else active
        status_map[name] = CommandResult(ok, argv, result.returncode, stdout_text, description)
    return status_map


def daemon_reload(timeout: int = 30) -> CommandResult:
    argv = ["systemctl", "daemon-reload"]
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
        result = CommandResult(completed.returncode == 0, argv, completed.returncode, completed.stdout, completed.stderr)
    except (OSError, subprocess.TimeoutExpired) as exc:
        result = CommandResult(False, argv, None, "", f"{type(exc).__name__}: {exc}")
    _log_result("systemctl.daemon_reload", result)
    return result


def read_unit_journal(unit_name: str, lines: int = 200) -> CommandResult:
    lines = max(1, min(lines, 500))
    argv = ["journalctl", "-u", unit_name, "-n", str(lines), "--no-pager"]
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=20, check=False)
        result = CommandResult(completed.returncode == 0, argv, completed.returncode, completed.stdout, completed.stderr)
    except (OSError, subprocess.TimeoutExpired) as exc:
        result = CommandResult(False, argv, None, "", f"{type(exc).__name__}: {exc}")
    _log_result("systemctl.journal", result)
    return result


def read_journal(settings: AppSettings, lines: int = 200) -> CommandResult:
    lines = max(1, min(lines, 500))
    argv = ["journalctl"]
    if settings.service_scope == "user":
        argv.append("--user")
    argv.extend(["-u", settings.llama_service_name, "-n", str(lines), "--no-pager"])
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=20, check=False)
        result = CommandResult(completed.returncode == 0, argv, completed.returncode, completed.stdout, completed.stderr)
    except (OSError, subprocess.TimeoutExpired) as exc:
        result = CommandResult(False, argv, None, "", f"{type(exc).__name__}: {exc}")
    _log_result("systemctl.journal", result)
    return result


def probe_binary(settings: AppSettings) -> dict[str, object]:
    result: dict[str, object] = {"platform": platform.system(), "version": None, "devices": [], "errors": []}
    for flag, key, timeout in [("--version", "version", 15), ("--list-devices", "devices", 20)]:
        try:
            completed = subprocess.run(
                [settings.llama_server_bin, flag], capture_output=True, text=True, timeout=timeout, check=False
            )
            output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
            if completed.returncode != 0:
                result["errors"].append(f"{flag}: {output or 'exit ' + str(completed.returncode)}")
            elif key == "devices":
                result[key] = [line.strip() for line in output.splitlines() if line.strip()]
            else:
                result[key] = output
        except (OSError, subprocess.TimeoutExpired) as exc:
            result["errors"].append(f"{flag}: {exc}")
    return result
