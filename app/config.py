"""Zentrale Konfiguration für Kiara."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Aus Umgebungsvariablen / .env geladene Einstellungen."""

    model_config = SettingsConfigDict(
        env_prefix="KIARA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Path("./data")
    secret_key: str = ""
    max_fetch: int = 0
    # 127.0.0.1 = nur dieser Rechner; 0.0.0.0 = im Heimnetz erreichbar
    # (z.B. für den Zugriff von einem zweiten MacBook aus).
    host: str = "127.0.0.1"
    port: int = 8000
    # True, wenn Kiara hinter HTTPS läuft (z.B. Caddy/nginx als Reverse-Proxy):
    # Session-Cookies werden dann nur über HTTPS übertragen.
    secure_cookies: bool = False
    # Sprachen für die Texterkennung (Tesseract), z.B. "deu+eng".
    ocr_lang: str = "deu+eng"
    # Automatischer Sync aller aktiven Konten alle N Minuten (0 = aus).
    sync_interval_minutes: int = 30

    @property
    def db_path(self) -> Path:
        return self.data_dir / "kiara.sqlite"

    @property
    def attachments_dir(self) -> Path:
        return self.data_dir / "attachments"

    @property
    def statements_dir(self) -> Path:
        return self.data_dir / "statements"

    @property
    def key_file(self) -> Path:
        return self.data_dir / ".kiara_key"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.attachments_dir.mkdir(parents=True, exist_ok=True)
        self.statements_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
