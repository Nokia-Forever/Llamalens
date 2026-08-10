from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class LaunchModelInput(BaseModel):
    alias: str = Field(min_length=1, max_length=200)
    model_path: str = ""
    display_name: str = ""
    enabled: bool = True

    @field_validator("alias")
    @classmethod
    def validate_launch_alias(cls, value: str) -> str:
        value = value.strip()
        if not value or any(char.isspace() for char in value):
            raise ValueError("模型 alias 不能为空或包含空白字符")
        return value


class LaunchConfig(BaseModel):
    mode: Literal["single", "router"] = "single"
    model_path: str = ""
    model_alias: str = ""
    models_dir: str = ""
    models_preset: str = ""
    models_max: int = Field(default=0, ge=0)
    models_autoload: bool = False
    models: list[LaunchModelInput] = Field(default_factory=list)
    catalog_args: list[CatalogArgumentInput] = Field(default_factory=list)
    custom_args_text: str = ""
    labels: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_launch_config(self):
        if self.mode == "single":
            if not self.model_path.strip():
                raise ValueError("单模型 Profile 必须设置模型路径")
            if not self.model_alias.strip() or any(char.isspace() for char in self.model_alias):
                raise ValueError("单模型 Profile 必须设置不含空白的 alias")
        else:
            if not self.models_dir.strip():
                raise ValueError("Router Profile 必须设置 models directory")
            enabled = [item for item in self.models if item.enabled]
            if not enabled:
                raise ValueError("Router Profile 至少需要一个启用的模型 alias")
            aliases = [item.alias for item in enabled]
            if len(aliases) != len(set(aliases)):
                raise ValueError("同一 Profile 中的模型 alias 不能重复")
        return self


class ProfileCreate(LaunchConfig):
    name: str = Field(min_length=1, max_length=200)


class ProfileUpdate(ProfileCreate):
    pass


class ProfileOut(ProfileCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    final_argv: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class BenchmarkCreate(BaseModel):
    name: str = "Benchmark"
    service_id: str | None = None
    model_alias: str | None = None
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
    repeat_delay_ms: int = Field(default=0, ge=0, le=600000)
    concurrency: int = Field(default=1, ge=1, le=128)
    extra_params: dict[str, Any] = Field(default_factory=dict)


class BenchmarkBulkDelete(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=200)


class TaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    service_id: str
    model_alias: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1)
    max_tokens: int = Field(default=256, ge=1, le=131072)
    timeout_seconds: float = Field(default=300, gt=0, le=86400)
    temperature: float = Field(default=0, ge=0, le=10)
    seed: int | None = 42
    stop: list[str] = Field(default_factory=list)
    cache_prompt: bool = False
    warmup_runs: int = Field(default=1, ge=0, le=100)
    repeat_runs: int = Field(default=3, ge=1, le=100)
    repeat_delay_ms: int = Field(default=0, ge=0, le=600000)
    concurrency: int = Field(default=1, ge=1, le=128)
    extra_params: dict[str, Any] = Field(default_factory=dict)


class TaskUpdate(TaskCreate):
    pass


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    service_id: str
    model_alias: str
    config: dict[str, Any]
    last_run_status: str | None = None
    run_count: int = 0
    created_at: datetime
    updated_at: datetime


class QueuePatch(BaseModel):
    status: Literal["start", "pause"] | None = None
    interval_ms: int | None = Field(default=None, ge=0, le=86400000)
    cancel_timeout_ms: int | None = Field(default=None, ge=1000, le=600000)


class QueueItemCreate(BaseModel):
    task_id: str
    position: Literal["tail", "head"] | int = "tail"


class ReorderInput(BaseModel):
    item_ids: list[str] = Field(min_length=1, max_length=500)


class DownloadCreate(BaseModel):
    url: str = Field(pattern=r"^https?://")
    target_root: str
    filename: str = Field(min_length=1, max_length=512)


class ServiceAction(BaseModel):
    action: Literal["start", "stop", "restart", "status"]


class ServiceModelInput(BaseModel):
    alias: str = Field(min_length=1, max_length=200)
    model_path: str = ""
    display_name: str = ""
    enabled: bool = True

    @field_validator("alias")
    @classmethod
    def validate_alias(cls, value: str) -> str:
        value = value.strip()
        if not value or any(char.isspace() for char in value):
            raise ValueError("模型 alias 不能为空或包含空白字符")
        return value


class LlamaServiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    unit_name: str = ""
    server_bin: str = Field(min_length=1)
    service_user: str = "root"
    service_group: str = "root"
    working_directory: str = "/"
    host: str = "127.0.0.1"
    port: int = 8080
    health_path: str = "/health"
    request_path: str = "/completion"
    unit_extra_text: str = ""
    service_extra_text: str = ""
    install_extra_text: str = ""

    @field_validator("port")
    @classmethod
    def validate_service_port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("端口必须在 1-65535 之间")
        return value


class LlamaServiceUpdate(LlamaServiceCreate):
    pass


class SelectProfileInput(BaseModel):
    profile_id: str
