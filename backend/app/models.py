from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SettingsRecord(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ArgumentCatalog(Base):
    __tablename__ = "argument_catalog"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    aliases_json: Mapped[str] = mapped_column(Text, default="[]")
    value_hint: Mapped[str] = mapped_column(String(120), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(80), default="other", index=True)
    source: Mapped[str] = mapped_column(String(32), default="builtin")
    supported: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ModelFile(Base):
    __tablename__ = "model_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(String(512), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    quantization: Mapped[str | None] = mapped_column(String(80), nullable=True)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DownloadJob(Base):
    __tablename__ = "download_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    url: Mapped[str] = mapped_column(Text)
    target_path: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    downloaded_bytes: Mapped[int] = mapped_column(Integer, default=0)
    total_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    model_path: Mapped[str] = mapped_column(Text)
    catalog_args_json: Mapped[str] = mapped_column(Text, default="[]")
    custom_args_text: Mapped[str] = mapped_column(Text, default="")
    labels_json: Mapped[str] = mapped_column(Text, default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    versions: Mapped[list["ProfileVersion"]] = relationship(back_populates="profile", cascade="all, delete-orphan")


class ProfileVersion(Base):
    __tablename__ = "profile_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    spec_json: Mapped[str] = mapped_column(Text)
    argv_json: Mapped[str] = mapped_column(Text)
    binary_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    profile: Mapped[Profile] = relationship(back_populates="versions")


class SwitchJob(Base):
    __tablename__ = "switch_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    diagnostics_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BenchmarkJob(Base):
    __tablename__ = "benchmark_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="Benchmark")
    profile_id: Mapped[str | None] = mapped_column(ForeignKey("profiles.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    config_json: Mapped[str] = mapped_column(Text)
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[list["BenchmarkAttempt"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class BenchmarkAttempt(Base):
    __tablename__ = "benchmark_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("benchmark_jobs.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    warmup: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="running")
    request_json: Mapped[str] = mapped_column(Text)
    raw_response_json: Mapped[str] = mapped_column(Text, default="{}")
    measurement_mode: Mapped[str] = mapped_column(String(32), default="stream")
    ttft_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    prefill_tps: Mapped[float | None] = mapped_column(Float, nullable=True)
    decode_tps: Mapped[float | None] = mapped_column(Float, nullable=True)
    client_decode_tps: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    predicted_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resource_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    job: Mapped[BenchmarkJob] = relationship(back_populates="attempts")
