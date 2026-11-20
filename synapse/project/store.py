"""Project persistence: save, open, autosave and crash recovery."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from .model import Project, ProjectError
from .settings import AppDatabase, app_data_dir

PROJECT_SUFFIX = ".synapse"


class ProjectStore:
    """Reads and writes ``.synapse`` files and keeps recovery snapshots.

    Writes go to a temporary file in the same directory and are moved into
    place with :func:`os.replace`, so an interrupted save cannot truncate the
    project the user already had on disk.
    """

    def __init__(self, database: AppDatabase | None = None, *, autosave_dir: str | None = None) -> None:
        self.database = database
        self.autosave_dir = Path(autosave_dir) if autosave_dir else app_data_dir() / "autosave"
        self.autosave_dir.mkdir(parents=True, exist_ok=True)

    # -- paths ----------------------------------------------------------
    @staticmethod
    def normalize_path(path: str | os.PathLike) -> Path:
        target = Path(path).expanduser()
        if target.suffix != PROJECT_SUFFIX:
            target = target.with_suffix(PROJECT_SUFFIX)
        return target

    def _recovery_path(self, path: Path) -> Path:
        digest = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:16]
        return self.autosave_dir / f"{digest}.autosave"

    # -- save / open ----------------------------------------------------
    def save(self, project: Project, path: str | os.PathLike | None = None, *, make_backup: bool = True) -> Path:
        target = self.normalize_path(path or project.path or (project.name + PROJECT_SUFFIX))
        target.parent.mkdir(parents=True, exist_ok=True)
        project.modified = time.time()
        payload = project.to_dict()
        text = json.dumps(payload, indent=2, ensure_ascii=False)

        if target.exists() and make_backup:
            backup = target.with_suffix(target.suffix + ".bak")
            try:
                backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
            except OSError:
                pass

        temp = target.with_suffix(target.suffix + ".tmp")
        with open(temp, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)

        project.path = str(target)
        self.clear_recovery(target)
        if self.database is not None:
            self.database.add_recent(str(target), project.name)
        return target

    def load(self, path: str | os.PathLike, *, registry=None) -> Project:
        target = Path(path).expanduser()
        try:
            text = target.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ProjectError(f"project file not found: {target}") from exc
        except OSError as exc:
            raise ProjectError(f"cannot read {target}: {exc}") from exc
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProjectError(f"{target.name} is not valid JSON: {exc}") from exc
        project = Project.from_dict(data, registry=registry, path=str(target))
        project.bind_registry(registry) if registry is not None else None
        return project

    def exists(self, path: str | os.PathLike) -> bool:
        return self.normalize_path(path).exists()

    # -- autosave and recovery ------------------------------------------
    def autosave(self, project: Project) -> Path | None:
        """Store a recovery snapshot for the project's current path."""
        if not project.path:
            return None
        snapshot = self._recovery_path(Path(project.path))
        data: dict[str, Any] = {
            "saved_at": time.time(),
            "path": project.path,
            "project": project.to_dict(),
        }
        temp = snapshot.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, snapshot)
        return snapshot

    def clear_recovery(self, path: str | os.PathLike) -> None:
        snapshot = self._recovery_path(Path(path))
        if snapshot.exists():
            try:
                snapshot.unlink()
            except OSError:
                pass

    def recovery_for(self, path: str | os.PathLike) -> dict | None:
        snapshot = self._recovery_path(Path(path))
        if not snapshot.exists():
            return None
        try:
            return json.loads(snapshot.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def recoveries(self) -> list[dict]:
        """Every recovery snapshot, newest first."""
        items = []
        for snapshot in self.autosave_dir.glob("*.autosave"):
            try:
                data = json.loads(snapshot.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            project = data.get("project") or {}
            items.append(
                {
                    "snapshot": str(snapshot),
                    "path": data.get("path"),
                    "saved_at": float(data.get("saved_at") or 0),
                    "name": project.get("name") or Path(str(data.get("path") or "project")).stem,
                }
            )
        items.sort(key=lambda item: item["saved_at"], reverse=True)
        return items

    def load_recovery(self, snapshot: str | os.PathLike, *, registry=None) -> Project:
        data = json.loads(Path(snapshot).read_text(encoding="utf-8"))
        project = Project.from_dict(data.get("project") or {}, registry=registry, path=data.get("path"))
        if registry is not None:
            project.bind_registry(registry)
        return project

    def discard_recovery(self, snapshot: str | os.PathLike) -> None:
        try:
            Path(snapshot).unlink()
        except OSError:
            pass

    # -- json helpers ---------------------------------------------------
    @staticmethod
    def dumps(project: Project) -> str:
        return json.dumps(project.to_dict(), indent=2, ensure_ascii=False)

    @staticmethod
    def loads(text: str, *, registry=None, path: str | None = None) -> Project:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProjectError(f"invalid project JSON: {exc}") from exc
        return Project.from_dict(data, registry=registry, path=path)
