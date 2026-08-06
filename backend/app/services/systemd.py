from __future__ import annotations

import platform
import shlex
import subprocess
from dataclasses import dataclass

from app.schemas import AppSettings


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
        return CommandResult(completed.returncode == 0, argv, completed.returncode, completed.stdout, completed.stderr)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandResult(False, argv, None, "", f"{type(exc).__name__}: {exc}")


def read_journal(settings: AppSettings, lines: int = 200) -> CommandResult:
    lines = max(1, min(lines, 500))
    argv = ["journalctl"]
    if settings.service_scope == "user":
        argv.append("--user")
    argv.extend(["-u", settings.llama_service_name, "-n", str(lines), "--no-pager"])
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=20, check=False)
        return CommandResult(completed.returncode == 0, argv, completed.returncode, completed.stdout, completed.stderr)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandResult(False, argv, None, "", f"{type(exc).__name__}: {exc}")


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
