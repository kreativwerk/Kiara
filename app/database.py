"""Datenbank-Setup (SQLAlchemy + SQLite)."""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy import event as sa_event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()

engine = create_engine(
    f"sqlite:///{settings.db_path}",
    connect_args={"check_same_thread": False},
    future=True,
)


@sa_event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _record) -> None:
    """WAL-Modus + Warte-Timeout: verhindert 'database is locked' bei
    gleichzeitigen Zugriffen (z.B. Hintergrund-Sync + Weboberfläche)."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _ensure_columns(target_engine) -> None:
    """Mini-Migration: ergänzt fehlende (nullable) Spalten in bestehenden Tabellen.

    ``create_all`` legt nur neue Tabellen an. Kommt in einer neuen Version eine
    Spalte hinzu, ergänzt dieser Schritt sie per ``ALTER TABLE`` – so überleben
    bestehende Datenbanken ein Update ohne manuelle Migration.
    """
    import sqlalchemy as sa

    inspector = sa.inspect(target_engine)
    with target_engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                col_type = column.type.compile(target_engine.dialect)
                conn.execute(
                    sa.text(f'ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type}')
                )


def init_db() -> None:
    """Erstellt alle Tabellen (idempotent) und ergänzt fehlende Spalten."""
    from . import models  # noqa: F401  (Modelle registrieren)

    Base.metadata.create_all(bind=engine)
    _ensure_columns(engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI-Dependency für eine DB-Session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
