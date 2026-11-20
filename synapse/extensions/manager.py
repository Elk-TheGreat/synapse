"""Plugin discovery, installation and loading."""

from __future__ import annotations

import importlib.util
import shutil
import sys
import traceback
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from ..nodes.registry import NodeRegistry
from ..project.settings import AppDatabase, app_data_dir
from .api import PluginAPI, build_script_node
from .manifest import ManifestError, PluginManifest

BUILTIN_PLUGIN_DIRS = ("text-tools", "stats")


class PluginError(RuntimeError):
    """Installing, removing or loading a plugin failed."""


@dataclass
class PluginRecord:
    manifest: PluginManifest
    enabled: bool
    location: str
    source: str = "user"  # user | bundled
    error: str | None = None
    node_count: int = 0
    extra: dict = field(default_factory=dict)


def user_plugin_dir() -> Path:
    return app_data_dir() / "plugins"


def bundled_plugin_dir() -> Path:
    return Path(__file__).resolve().parent / "bundled"


class PluginManager:
    def __init__(self, database: AppDatabase | None = None, *, roots: list[Path] | None = None) -> None:
        self.database = database
        self.user_dir = user_plugin_dir()
        self.user_dir.mkdir(parents=True, exist_ok=True)
        self.roots = roots or [bundled_plugin_dir(), self.user_dir]
        self.records: dict[str, PluginRecord] = {}
        self._modules: dict[str, object] = {}

    # -- discovery ------------------------------------------------------
    def discover(self) -> list[PluginRecord]:
        self.records.clear()
        for root in self.roots:
            if not root.is_dir():
                continue
            for folder in sorted(root.iterdir()):
                if not folder.is_dir() or folder.name.startswith((".", "_")):
                    continue
                try:
                    manifest = PluginManifest.load(folder)
                except ManifestError as exc:
                    self.records[folder.name] = PluginRecord(
                        manifest=PluginManifest(name=folder.name, version="?", directory=folder),
                        enabled=False,
                        location=str(folder),
                        source="bundled" if root == self.roots[0] else "user",
                        error=str(exc),
                    )
                    continue
                source = "bundled" if root == self.roots[0] else "user"
                enabled = self._enabled_state(manifest.name, source)
                self.records[manifest.name] = PluginRecord(
                    manifest=manifest,
                    enabled=enabled,
                    location=str(folder),
                    source=source,
                )
        return self.list()

    def _enabled_state(self, name: str, source: str) -> bool:
        stored = None
        if self.database is not None:
            for row in self.database.plugins():
                if row["name"] == name:
                    stored = bool(row["enabled"])
                    break
        return True if stored is None and source == "bundled" else bool(stored)

    def list(self) -> list[PluginRecord]:
        return sorted(self.records.values(), key=lambda record: record.manifest.title.lower())

    def get(self, name: str) -> PluginRecord | None:
        return self.records.get(name)

    # -- enable / disable -----------------------------------------------
    def set_enabled(self, name: str, enabled: bool) -> None:
        record = self.records.get(name)
        if record is None:
            raise PluginError(f"unknown plugin '{name}'")
        record.enabled = enabled
        if self.database is not None:
            self.database.record_plugin(record.manifest.name, record.manifest.version, enabled)

    # -- install / remove -----------------------------------------------
    def install(self, source: str | Path, *, replace: bool = False) -> PluginRecord:
        src = Path(source)
        if not src.exists():
            raise PluginError(f"{src} does not exist")
        staging = self.user_dir / f".staging-{src.stem}"
        if staging.exists():
            shutil.rmtree(staging)
        try:
            if src.is_file() and zipfile.is_zipfile(src):
                staging.mkdir(parents=True)
                with zipfile.ZipFile(src) as archive:
                    for member in archive.namelist():
                        target = (staging / member).resolve()
                        if not str(target).startswith(str(staging.resolve())):
                            raise PluginError("archive contains an unsafe path")
                    archive.extractall(staging)
            elif src.is_dir():
                shutil.copytree(src, staging)
            else:
                raise PluginError("install expects a plugin folder or a .zip archive")
            if not (staging / "plugin.json").is_file():
                nested = [p for p in staging.iterdir() if p.is_dir() and (p / "plugin.json").is_file()]
                if len(nested) == 1:
                    staging = nested[0]
                else:
                    raise PluginError("plugin.json not found in the package root")
            manifest = PluginManifest.load(staging)
            target = self.user_dir / manifest.name
            if target.exists():
                if not replace:
                    raise PluginError(f"plugin '{manifest.name}' is already installed")
                shutil.rmtree(target)
            shutil.move(str(staging), str(target))
            manifest.directory = target
            record = PluginRecord(manifest, enabled=True, location=str(target), source="user")
            self.records[manifest.name] = record
            if self.database is not None:
                self.database.record_plugin(manifest.name, manifest.version, True)
            return record
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

    def remove(self, name: str) -> None:
        record = self.records.get(name)
        if record is None:
            raise PluginError(f"unknown plugin '{name}'")
        if record.source == "bundled":
            raise PluginError("bundled plugins cannot be removed; disable them instead")
        shutil.rmtree(record.location, ignore_errors=True)
        self.records.pop(name, None)
        if self.database is not None:
            self.database._conn.execute("DELETE FROM plugins WHERE name = ?", (name,))
            self.database._conn.commit()

    # -- loading --------------------------------------------------------
    def load_enabled(self, registry: NodeRegistry) -> dict[str, str]:
        """Register nodes of every enabled plugin.

        Returns a mapping ``plugin -> error`` for plugins that failed.  A broken
        plugin never prevents the others (or the application) from starting.
        """
        failures: dict[str, str] = {}
        for record in self.list():
            if not record.enabled:
                continue
            try:
                count = self._load_one(record, registry)
                record.node_count = count
                record.error = None
            except Exception as exc:  # plugin code is untrusted: contain all failures
                record.error = f"{type(exc).__name__}: {exc}"
                failures[record.manifest.name] = record.error
                record.node_count = 0
                detail = traceback.format_exc()
                if self.database is not None:
                    self.database.set(f"plugin.last_error.{record.manifest.name}", detail)
        return failures

    def _load_one(self, record: PluginRecord, registry: NodeRegistry) -> int:
        manifest = record.manifest
        if manifest.directory is None:
            raise PluginError("plugin has no directory")
        if manifest.runtime == "script":
            if not manifest.nodes:
                raise PluginError("script plugin declares no nodes")
            for spec in manifest.nodes:
                registry.register(build_script_node(manifest, spec))
            return len(manifest.nodes)
        entry = manifest.entry_path
        if not entry.is_file():
            raise PluginError(f"entry module {manifest.entry} is missing")
        module_name = "synapse_plugin_" + "".join(ch if ch.isalnum() else "_" for ch in manifest.name)
        spec = importlib.util.spec_from_file_location(module_name, entry)
        if spec is None or spec.loader is None:
            raise PluginError(f"cannot import {entry}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise
        register = getattr(module, "register", None)
        if not callable(register):
            raise PluginError("plugin module must define register(registry, api)")
        api = PluginAPI(manifest, registry)
        register(registry, api)
        self._modules[manifest.name] = module
        return len(api.registered)
