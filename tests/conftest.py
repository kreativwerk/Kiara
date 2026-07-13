"""Test-Setup: isoliertes Datenverzeichnis pro Testlauf."""
from __future__ import annotations

import os
import tempfile

# WICHTIG: vor dem Import der App-Module gesetzt, damit die Settings
# (lru_cache) das temporäre Verzeichnis verwenden.
_TMP = tempfile.mkdtemp(prefix="kiara-test-")
os.environ["KIARA_DATA_DIR"] = _TMP
os.environ["KIARA_SECRET_KEY"] = "A" * 43 + "="  # gültiger 32-Byte Fernet-Key (base64)

import pytest  # noqa: E402

from app.database import Base, SessionLocal, engine, init_db  # noqa: E402


def _truncate() -> None:
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture(scope="session", autouse=True)
def _db_setup():
    init_db()
    yield


@pytest.fixture
def db():
    _truncate()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    _truncate()
    with TestClient(app) as test_client:
        yield test_client
