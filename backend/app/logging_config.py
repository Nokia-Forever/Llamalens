from __future__ import annotations

import json
import logging
import logging.config
import os
from datetime import datetime, timezone


_RESERVED_ATTRS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName", "processName",
    "process", "taskName", "message", "asctime",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        message = record.getMessage()
        payload: dict[str, object] = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "event": record.__dict__.get("event", message),
            "msg": message,
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED_ATTRS or key in payload or key.startswith("_"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _level_from_env(default: str = "INFO") -> str:
    level = os.getenv("LLAMALENS_LOG_LEVEL", default).strip().upper()
    if not level:
        return default
    return level


def _build_config(level: str) -> dict:
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"json": {"()": "app.logging_config.JsonFormatter"}},
        "handlers": {
            "stdout": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "json",
            },
        },
        "loggers": {
            "uvicorn": {"level": level, "handlers": ["stdout"], "propagate": False},
            "uvicorn.access": {"level": level, "handlers": ["stdout"], "propagate": False},
            "uvicorn.error": {"level": level, "handlers": ["stdout"], "propagate": False},
            "sqlalchemy": {"level": "WARNING", "handlers": ["stdout"], "propagate": False},
        },
        "root": {"level": level, "handlers": ["stdout"]},
    }


LOGGING_CONFIG: dict = _build_config("INFO")


def setup_logging(level: str | None = None) -> None:
    logging.config.dictConfig(_build_config((level or _level_from_env()).upper()))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
