from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker


def _database_url() -> str:
    explicit = os.getenv("LLAMALENS_DATABASE_URL")
    if explicit:
        return explicit
    data_dir = Path(os.getenv("LLAMALENS_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(data_dir / 'llamalens.db').as_posix()}"


DATABASE_URL = _database_url()
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
)


if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_legacy_columns()


def _migrate_legacy_columns() -> None:
    """Small SQLite-compatible migration for databases created by the V1 app."""
    inspector = inspect(engine)
    if "profiles" in inspector.get_table_names():
        profile_columns = {column["name"] for column in inspector.get_columns("profiles")}
        if "service_id" not in profile_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE profiles ADD COLUMN service_id VARCHAR(36)"))
                connection.execute(text("CREATE INDEX IF NOT EXISTS ix_profiles_service_id ON profiles (service_id)"))
        if "model_alias" not in profile_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE profiles ADD COLUMN model_alias VARCHAR(200) DEFAULT ''"))
        profile_additions = {
            "mode": "ALTER TABLE profiles ADD COLUMN mode VARCHAR(32) DEFAULT 'single'",
            "models_dir": "ALTER TABLE profiles ADD COLUMN models_dir TEXT DEFAULT ''",
            "models_preset": "ALTER TABLE profiles ADD COLUMN models_preset TEXT DEFAULT ''",
            "models_max": "ALTER TABLE profiles ADD COLUMN models_max INTEGER DEFAULT 0",
            "models_autoload": "ALTER TABLE profiles ADD COLUMN models_autoload BOOLEAN DEFAULT 0",
        }
        missing_profile_additions = [statement for name, statement in profile_additions.items() if name not in profile_columns]
        if missing_profile_additions:
            with engine.begin() as connection:
                for statement in missing_profile_additions:
                    connection.execute(text(statement))
    inspector = inspect(engine)
    if "llama_services" in inspector.get_table_names():
        service_columns = {column["name"] for column in inspector.get_columns("llama_services")}
        service_additions = {
            "source_profile_id": "ALTER TABLE llama_services ADD COLUMN source_profile_id VARCHAR(36)",
            "applied_source_profile_id": "ALTER TABLE llama_services ADD COLUMN applied_source_profile_id VARCHAR(36)",
            "draft_launch_config_json": "ALTER TABLE llama_services ADD COLUMN draft_launch_config_json TEXT DEFAULT ''",
            "applied_launch_config_json": "ALTER TABLE llama_services ADD COLUMN applied_launch_config_json TEXT DEFAULT ''",
            "applied_service_config_json": "ALTER TABLE llama_services ADD COLUMN applied_service_config_json TEXT DEFAULT ''",
        }
        missing_service_additions = [statement for name, statement in service_additions.items() if name not in service_columns]
        if missing_service_additions:
            with engine.begin() as connection:
                for statement in missing_service_additions:
                    connection.execute(text(statement))
                connection.execute(text("CREATE INDEX IF NOT EXISTS ix_llama_services_source_profile_id ON llama_services (source_profile_id)"))
                connection.execute(text("CREATE INDEX IF NOT EXISTS ix_llama_services_applied_source_profile_id ON llama_services (applied_source_profile_id)"))
    inspector = inspect(engine)
    if "benchmark_jobs" in inspector.get_table_names():
        benchmark_columns = {column["name"] for column in inspector.get_columns("benchmark_jobs")}
        additions = []
        if "service_id" not in benchmark_columns:
            additions.append("ALTER TABLE benchmark_jobs ADD COLUMN service_id VARCHAR(36)")
        if "model_alias" not in benchmark_columns:
            additions.append("ALTER TABLE benchmark_jobs ADD COLUMN model_alias VARCHAR(200)")
        if additions:
            with engine.begin() as connection:
                for statement in additions:
                    connection.execute(text(statement))
                connection.execute(text("CREATE INDEX IF NOT EXISTS ix_benchmark_jobs_service_id ON benchmark_jobs (service_id)"))
                connection.execute(text("CREATE INDEX IF NOT EXISTS ix_benchmark_jobs_model_alias ON benchmark_jobs (model_alias)"))


def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
