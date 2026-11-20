"""Plugin manifest: ``plugin.json`` next to a plugin's Python module.

Example::

    {
      "name": "acme.text-tools",
      "display_name": "ACME Text Tools",
      "version": "1.0.0",
      "api_version": 1,
      "description": "Extra string nodes",
      "author": "ACME",
      "entry": "nodes.py",
      "runtime": "python",
      "permissions": ["files"],
      "dependencies": [],
      "keywords": ["text"]
    }

``runtime`` is ``python`` (loaded in-process, so it has the capabilities of the
host process and must be installed deliberately) or ``script`` (each node's
code runs in the isolated interpreter with an import allow-list, see
``documentation/PLUGINS.md``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

PLUGIN_API_VERSION = 1
PERMISSIONS = ("files", "network", "process", "scripts")
RUNTIMES = ("python", "script")


class ManifestError(ValueError):
    """``plugin.json`` is missing, malformed or incompatible."""


@dataclass
class PluginNodeSpec:
    type_id: str
    name: str
    category: str = "Extensions"
    description: str = ""
    inputs: list[dict] = field(default_factory=list)
    outputs: list[dict] = field(default_factory=list)
    params: list[dict] = field(default_factory=list)
    code: str = ""
    pure: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> "PluginNodeSpec":
        if not data.get("type_id"):
            raise ManifestError("a node spec needs a type_id")
        return cls(
            type_id=str(data["type_id"]),
            name=str(data.get("name") or data["type_id"]),
            category=str(data.get("category") or "Extensions"),
            description=str(data.get("description") or ""),
            inputs=list(data.get("inputs") or []),
            outputs=list(data.get("outputs") or []),
            params=list(data.get("params") or []),
            code=str(data.get("code") or ""),
            pure=bool(data.get("pure", True)),
        )

    def to_dict(self) -> dict:
        return {
            "type_id": self.type_id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "params": self.params,
            "code": self.code,
            "pure": self.pure,
        }


@dataclass
class PluginManifest:
    name: str
    version: str
    api_version: int = PLUGIN_API_VERSION
    display_name: str = ""
    description: str = ""
    author: str = ""
    entry: str = "nodes.py"
    runtime: str = "python"
    permissions: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    nodes: list[PluginNodeSpec] = field(default_factory=list)
    directory: Path | None = None
    enabled: bool = False

    @property
    def title(self) -> str:
        return self.display_name or self.name

    @property
    def entry_path(self) -> Path:
        if self.directory is None:
            raise ManifestError("manifest is not attached to a directory")
        return self.directory / self.entry

    def compatibility_problem(self, host_api_version: int = PLUGIN_API_VERSION) -> str | None:
        if self.api_version > host_api_version:
            return (
                f"plugin API {self.api_version} is newer than this SYNAPSE "
                f"(API {host_api_version})"
            )
        if self.runtime not in RUNTIMES:
            return f"unknown runtime '{self.runtime}' (expected one of {', '.join(RUNTIMES)})"
        unknown = [p for p in self.permissions if p not in PERMISSIONS]
        if unknown:
            return f"unknown permissions: {', '.join(unknown)}"
        return None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "version": self.version,
            "api_version": self.api_version,
            "description": self.description,
            "author": self.author,
            "entry": self.entry,
            "runtime": self.runtime,
            "permissions": list(self.permissions),
            "dependencies": list(self.dependencies),
            "keywords": list(self.keywords),
            "nodes": [node.to_dict() for node in self.nodes],
        }

    @classmethod
    def from_dict(cls, data: dict, *, directory: Path | None = None) -> "PluginManifest":
        if not isinstance(data, dict):
            raise ManifestError("plugin.json must contain a JSON object")
        name = str(data.get("name") or "").strip()
        if not name:
            raise ManifestError("plugin.json needs a 'name'")
        version = str(data.get("version") or "").strip()
        if not version:
            raise ManifestError(f"plugin '{name}' needs a 'version'")
        runtime = str(data.get("runtime") or "python")
        if runtime not in RUNTIMES:
            raise ManifestError(f"plugin '{name}': unknown runtime '{runtime}'")
        entry = str(data.get("entry") or ("plugin.py" if runtime == "script" else "nodes.py"))
        if Path(entry).is_absolute() or ".." in Path(entry).parts:
            raise ManifestError(f"plugin '{name}': entry must stay inside the plugin folder")
        return cls(
            name=name,
            version=version,
            api_version=int(data.get("api_version") or 1),
            display_name=str(data.get("display_name") or ""),
            description=str(data.get("description") or ""),
            author=str(data.get("author") or ""),
            entry=entry,
            runtime=runtime,
            permissions=[str(p) for p in data.get("permissions") or []],
            dependencies=[str(d) for d in data.get("dependencies") or []],
            keywords=[str(k) for k in data.get("keywords") or []],
            nodes=[PluginNodeSpec.from_dict(item) for item in data.get("nodes") or []],
            directory=directory,
        )

    @classmethod
    def load(cls, directory: str | Path) -> "PluginManifest":
        folder = Path(directory)
        manifest_path = folder / "plugin.json"
        if not manifest_path.is_file():
            raise ManifestError(f"{folder} has no plugin.json")
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ManifestError(f"cannot read {manifest_path}: {exc}") from exc
        manifest = cls.from_dict(data, directory=folder)
        problem = manifest.compatibility_problem()
        if problem:
            raise ManifestError(f"plugin '{manifest.name}': {problem}")
        return manifest
