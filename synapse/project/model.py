"""Project document model.

One ``.synapse`` file holds a whole project as JSON: metadata, every graph,
the function library, settings and an asset manifest.  The schema is versioned
(``format_version``) and documented in ``documentation/PROJECT_FORMAT.md``.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..functions.library import FunctionDef, FunctionLibrary
from ..graph.model import Graph

FORMAT = "synapse.project"
FORMAT_VERSION = 1


class ProjectError(ValueError):
    """The project file is malformed or from an unsupported version."""


def new_project_id() -> str:
    return "prj_" + uuid.uuid4().hex[:12]


@dataclass
class ProjectSettings:
    theme: str = "dark"
    accent: str = "#5ac8fa"
    autosave_seconds: int = 60
    run_timeout: float = 120.0
    node_timeout: float = 60.0
    max_steps: int = 20_000
    concurrency: int = 8
    allow_network: bool = True
    allow_file_write: bool = True
    allow_process: bool = False
    allow_scripts: bool = True
    file_roots: list[str] = field(default_factory=list)
    allowed_hosts: list[str] = field(default_factory=list)
    editor: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data: dict | None) -> "ProjectSettings":
        settings = cls()
        for key, value in (data or {}).items():
            if hasattr(settings, key) and value is not None:
                setattr(settings, key, value)
        settings.autosave_seconds = max(5, int(settings.autosave_seconds))
        settings.concurrency = max(1, min(64, int(settings.concurrency)))
        return settings


@dataclass
class Project:
    id: str = field(default_factory=new_project_id)
    name: str = "Untitled"
    description: str = ""
    created: float = field(default_factory=time.time)
    modified: float = field(default_factory=time.time)
    graphs: dict[str, Graph] = field(default_factory=dict)
    functions: list[FunctionDef] = field(default_factory=list)
    settings: ProjectSettings = field(default_factory=ProjectSettings)
    assets: list[dict] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    path: str | None = None

    def __post_init__(self) -> None:
        if not self.graphs:
            self.graphs["g_main"] = Graph("g_main", "Main")

    @property
    def main_graph(self) -> Graph:
        first = next(iter(self.graphs.values()), None)
        if first is None:
            first = Graph("g_main", "Main")
            self.graphs[first.id] = first
        return first

    def graph(self, graph_id: str) -> Graph:
        try:
            return self.graphs[graph_id]
        except KeyError as exc:
            raise ProjectError(f"graph '{graph_id}' does not exist") from exc

    def add_graph(self, name: str, *, registry=None, graph_id: str | None = None) -> Graph:
        graph = Graph(graph_id, name, registry=registry)
        if graph.id in self.graphs:
            raise ProjectError(f"graph id '{graph.id}' is already used")
        self.graphs[graph.id] = graph
        self.touch()
        return graph

    def remove_graph(self, graph_id: str) -> Graph | None:
        if len(self.graphs) <= 1:
            raise ProjectError("a project needs at least one graph")
        graph = self.graphs.pop(graph_id, None)
        if graph is not None:
            self.touch()
        return graph

    def rename_graph(self, graph_id: str, name: str) -> None:
        self.graph(graph_id).name = name.strip() or "Untitled graph"
        self.touch()

    def touch(self) -> None:
        self.modified = time.time()

    # -- functions ------------------------------------------------------
    def function_library(self, registry=None, *, register: bool = True) -> FunctionLibrary:
        library = FunctionLibrary(registry)
        for function in self.functions:
            library.add(function, register=register)
        return library

    def add_function(self, function: FunctionDef, *, registry=None) -> FunctionDef:
        self.functions.append(function)
        if registry is not None:
            registry.register(function.to_definition(), replace=True)
        self.touch()
        return function

    def remove_function(self, function_id: str, *, registry=None) -> FunctionDef | None:
        for index, function in enumerate(self.functions):
            if function.id == function_id:
                self.functions.pop(index)
                if registry is not None:
                    registry.unregister(function.type_id)
                self.touch()
                return function
        return None

    def bind_registry(self, registry) -> None:
        """Point every graph at ``registry`` and expose this project's functions."""
        for graph in self.graphs.values():
            graph.set_registry(registry)
        for function in self.functions:
            function.graph.set_registry(registry)
            registry.register(function.to_definition(), replace=True)

    # -- assets ---------------------------------------------------------
    def relative_path(self, path: str) -> str:
        import os

        if not self.path:
            return path
        base = os.path.dirname(self.path)
        try:
            return os.path.relpath(path, base)
        except ValueError:
            return path

    # -- serialisation --------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "format": FORMAT,
            "format_version": FORMAT_VERSION,
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "created": self.created,
            "modified": self.modified,
            "settings": self.settings.to_dict(),
            "graphs": [graph.to_dict() for graph in self.graphs.values()],
            "functions": [function.to_dict() for function in self.functions],
            "assets": list(self.assets),
            "dependencies": list(self.dependencies),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict, *, registry=None, path: str | None = None) -> "Project":
        if not isinstance(data, dict):
            raise ProjectError("project file must contain a JSON object")
        fmt = data.get("format", FORMAT)
        if fmt != FORMAT:
            raise ProjectError(f"not a SYNAPSE project (format={fmt!r})")
        version = int(data.get("format_version", 0) or 0)
        if version > FORMAT_VERSION:
            raise ProjectError(
                f"project was written by a newer SYNAPSE (format {version}, supported {FORMAT_VERSION})"
            )
        graphs = {}
        for graph_data in data.get("graphs") or []:
            graph = Graph.from_dict(graph_data, registry=registry)
            if graph.id in graphs:
                raise ProjectError(f"duplicate graph id '{graph.id}'")
            graphs[graph.id] = graph
        functions = [
            FunctionDef.from_dict(item, registry=registry)
            for item in data.get("functions") or []
        ]
        project = cls(
            id=str(data.get("id") or new_project_id()),
            name=str(data.get("name") or "Untitled"),
            description=str(data.get("description") or ""),
            created=float(data.get("created") or time.time()),
            modified=float(data.get("modified") or time.time()),
            graphs=graphs,
            functions=functions,
            settings=ProjectSettings.from_dict(data.get("settings")),
            assets=list(data.get("assets") or []),
            dependencies=[str(d) for d in data.get("dependencies") or []],
            metadata=dict(data.get("metadata") or {}),
            path=path,
        )
        return project
