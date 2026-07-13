"""Tests für den (Google-freien) Kern der Drive-Spiegelung."""
from __future__ import annotations

from app.services.gdrive import DriveMirror, FolderResolver, split_relative


class FakeBackend:
    """Simuliert Google Drive im Speicher – ohne Netzwerk/Google-Libs."""

    def __init__(self) -> None:
        self.folders: dict[tuple[str, str], str] = {}  # (name, parent) -> id
        self.uploads: list[dict] = []
        self._counter = 0

    def _next_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}{self._counter}"

    def find_folder(self, name: str, parent_id: str) -> str | None:
        return self.folders.get((name, parent_id))

    def create_folder(self, name: str, parent_id: str) -> str:
        fid = self._next_id("folder")
        self.folders[(name, parent_id)] = fid
        return fid

    def upload(self, local_path: str, filename: str, parent_id: str, mimetype: str) -> str:
        fid = self._next_id("file")
        self.uploads.append(
            {"path": local_path, "name": filename, "parent": parent_id, "mime": mimetype, "id": fid}
        )
        return fid


def test_split_relative():
    assert split_relative("konto/2026/06/rechnung.pdf") == (
        ["konto", "2026", "06"],
        "rechnung.pdf",
    )
    assert split_relative("datei.pdf") == ([], "datei.pdf")
    # Windows-Trenner werden normalisiert
    assert split_relative("konto\\2026\\datei.pdf") == (["konto", "2026"], "datei.pdf")


def test_folder_resolver_creates_and_caches():
    backend = FakeBackend()
    resolver = FolderResolver(backend, root_id="root")

    first = resolver.ensure_path(["konto", "2026", "06"])
    second = resolver.ensure_path(["konto", "2026", "06"])
    assert first == second

    # Beim zweiten Mal darf kein neuer Ordner entstehen (Cache greift).
    assert len(backend.folders) == 3

    # Ein weiterer Monat teilt sich die oberen Ordner.
    resolver.ensure_path(["konto", "2026", "07"])
    assert len(backend.folders) == 4


def test_drive_mirror_upload_relative():
    backend = FakeBackend()
    mirror = DriveMirror(backend, root_id="root")

    file_id = mirror.upload_relative(
        "buchhaltung/2026/06/rechnung.pdf", "/local/rechnung.pdf", "application/pdf"
    )

    assert file_id.startswith("file")
    assert len(backend.uploads) == 1
    upload = backend.uploads[0]
    assert upload["name"] == "rechnung.pdf"
    assert upload["mime"] == "application/pdf"
    # Datei liegt im tiefsten Ordner (06), nicht in root.
    assert upload["parent"] != "root"
