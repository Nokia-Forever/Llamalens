from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path


TEST_DB = Path(tempfile.gettempdir()) / f"llamalens-pytest-{uuid.uuid4().hex}.db"
os.environ["LLAMALENS_DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"


import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def pytest_sessionfinish(session, exitstatus):
    engine.dispose()
    for suffix in ["", "-wal", "-shm"]:
        path = Path(f"{TEST_DB}{suffix}")
        if path.exists():
            path.unlink()
