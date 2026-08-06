from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AppSettings(BaseModel):
    llama_server_bin: str = "/usr/local/bin/llama-server"
    llama_service_name: str = "llama-server.service"
    llama_service_file: str = "/etc/systemd/system/llama-server.service"
    service_scope: Literal["system", "user"] = "system"
    service_control_command: str = "sudo -n systemctl"
    active_profile_path: str = "/var/lib/llama-lens/active-profile.json"
    model_roots: list[str] = Field(default_factory=lambda: ["/srv/models"])
    web_host: str = "127.0.0.1"
    web_port: int = 3000
    llama_host: str = "127.0.0.1"
    llama_port: int = 8080
    health_path: str = "/health"
    request_path: str = "/completion"
    download_timeout_seconds: int = 3600

    @field_validator("llama_service_name")
    @classmethod
    def validate_service_name(cls, value: str) -> str:
        import re

        if not re.fullmatch(r"[A-Za-z0-9_.@:-]+\.service", value):
            raise ValueError("service 名称必须是合法的 .service unit")
        return value

    @field_validator("web_port", "llama_port")
    @classmethod
    def validate_port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("端口必须在 1-65535 之间")
        return value

    @field_validator("service_control_command")
    @classmethod
    def validate_control_command(cls, value: str) -> str:
        import shlex

        parts = shlex.split(value, posix=True)
        allowed = [
            ["systemctl"],
            ["/usr/bin/systemctl"],
            ["sudo", "-n", "systemctl"],
            ["/usr/bin/sudo", "-n", "/usr/bin/systemctl"],
        ]
        if parts not in allowed:
            raise ValueError("控制命令只允许 systemctl 或 sudo -n systemctl 的固定形式")
        return value


class CatalogArgumentInput(BaseModel):
    flag: str
    value: str = ""


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    model_path: str = Field(min_length=1)
    catalog_args: list[CatalogArgumentInput] = Field(default_factory=list)
    custom_args_text: str = ""
    labels: dict[str, str] = Field(default_factory=dict)


class ProfileUpdate(ProfileCreate):
    pass


class ProfileOut(ProfileCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    is_active: bool
    final_argv: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class BenchmarkCreate(BaseModel):
    name: str = "Benchmark"
    profile_id: str | None = None
    prompt: str = Field(min_length=1)
    max_tokens: int = Field(default=256, ge=1, le=131072)
    timeout_seconds: float = Field(default=300, gt=0, le=86400)
    temperature: float = Field(default=0, ge=0, le=10)
    seed: int | None = 42
    stop: list[str] = Field(default_factory=list)
    cache_prompt: bool = False
    warmup_runs: int = Field(default=1, ge=0, le=100)
    repeat_runs: int = Field(default=3, ge=1, le=100)
    concurrency: int = Field(default=1, ge=1, le=128)
    extra_params: dict[str, Any] = Field(default_factory=dict)


class DownloadCreate(BaseModel):
    url: str = Field(pattern=r"^https?://")
    target_root: str
    filename: str = Field(min_length=1, max_length=512)


class ServiceAction(BaseModel):
    action: Literal["start", "stop", "restart", "status"]
