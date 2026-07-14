"""Test der Mini-Migration (_ensure_columns) für bestehende Datenbanken."""
from __future__ import annotations

import sqlalchemy as sa

from app.database import _ensure_columns


def test_ensure_columns_adds_missing(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path}/old.sqlite")
    # Simuliert eine alte Version: Tabelle existiert, aber ohne neue Spalten.
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE attachments ("
                "id INTEGER PRIMARY KEY, account_id INTEGER, filename VARCHAR(500), "
                "sha256 VARCHAR(64), stored_path TEXT)"
            )
        )

    _ensure_columns(engine)

    columns = {c["name"] for c in sa.inspect(engine).get_columns("attachments")}
    assert "text_content" in columns
    assert "drive_synced" in columns
    assert "detected_amount" in columns

    # Idempotent: zweiter Lauf ändert nichts und wirft nicht.
    _ensure_columns(engine)
