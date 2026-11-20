"""The API handed to third-party plugins.

A plugin never receives the node registry directly: it gets this object, which

* namespaces every type id under the plugin name,
* refuses to overwrite built-in nodes,
* checks declared permissions before the convenience helpers touch the system,
* records which plugin a node came from so the UI can label it.

Python plugins are ordinary Python and therefore run with the host process's
capabilities - installing one is an act of trust, and the UI shows exactly what
it asks for.  ``runtime: "script"`` plugins instead run each node's code in the
isolated interpreter used by the Python Script node.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Sequence

from ..nodes.base import ParamSpec, inp, make_definition, out
from ..nodes.registry import NodeRegistry
from ..scripting.runner import ScriptOptions, run_script
from ..typesystem import DataType
from .manifest import PluginManifest, PluginNodeSpec

log = logging.getLogger("synapse.extensions")


class PermissionDenied(PermissionError):
    """A plugin tried to use a capability it did not declare."""


class PluginAPI:
    def __init__(self, manifest: PluginManifest, registry: NodeRegistry) -> None:
        self.manifest = manifest
        self.registry = registry
        self.permissions = set(manifest.permissions)
        self.log = log.getChild(manifest.name)
        self.registered: list[str] = []

    # -- permissions ----------------------------------------------------
    def allowed(self, permission: str) -> bool:
        return permission in self.permissions

    def require(self, permission: str) -> None:
        if permission not in self.permissions:
            raise PermissionDenied(
                f"plugin '{self.manifest.name}' did not declare the '{permission}' permission"
            )

    # -- node registration ---------------------------------------------
    def node(
        self,
        type_id: str,
        name: str,
        category: str | None = None,
        *,
        description: str = "",
        inputs: Sequence[Any] = (),
        outputs: Sequence[Any] = (),
        params: Sequence[ParamSpec] = (),
        pure: bool = True,
        keywords: Sequence[str] = (),
    ) -> Callable:
        """Decorator: register ``fn`` as a node of this plugin."""

        def wrap(fn):
            self.register(
                fn,
                type_id,
                name,
                category or self.manifest.title,
                description=description,
                inputs=inputs,
                outputs=outputs,
                params=params,
                pure=pure,
                keywords=keywords,
            )
            return fn

        return wrap

    def register(
        self,
        fn,
        type_id: str,
        name: str,
        category: str | None = None,
        *,
        description: str = "",
        inputs: Sequence[Any] = (),
        outputs: Sequence[Any] = (),
        params: Sequence[ParamSpec] = (),
        pure: bool = True,
        keywords: Sequence[str] = (),
    ):
        full_id = self.namespaced(type_id)
        if self.registry.get(full_id) is not None:
            raise ValueError(f"node '{full_id}' is already registered")
        definition = make_definition(
            full_id,
            name,
            category or self.manifest.title,
            description=description,
            inputs=inputs,
            outputs=outputs,
            params=params,
            execute=fn,
            pure=pure,
            extension=self.manifest.name,
        )
        definition.keywords = tuple(keywords) + (self.manifest.name, "plugin")
        self.registry.register(definition)
        self.registered.append(full_id)
        return definition

    def namespaced(self, type_id: str) -> str:
        return type_id if type_id.startswith(f"ext.{self.manifest.name}.") else f"ext.{self.manifest.name}.{type_id}"

    # -- convenience types ---------------------------------------------
    @staticmethod
    def input(name: str, kind: DataType | str = DataType.ANY, default: Any = None):
        return inp(name, kind, default)

    @staticmethod
    def output(name: str, kind: DataType | str = DataType.ANY):
        return out(name, kind)

    @staticmethod
    def param(name: str, label: str, kind: str = "text", default: Any = None, **kwargs) -> ParamSpec:
        return ParamSpec(name, label, kind, default, **kwargs)

    # -- guarded system access ------------------------------------------
    def resolve_path(self, path: str, *, write: bool = False) -> Path:
        self.require("files")
        base = (self.manifest.directory or Path.cwd()).resolve()
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = (base / candidate).resolve()
        return candidate

    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        self.require("files")
        return self.resolve_path(path).read_text(encoding=encoding)


def _port_from_dict(spec: dict, *, output: bool):
    kind = spec.get("type") or spec.get("data_type") or "any"
    name = str(spec.get("name") or ("result" if output else "value"))
    default = spec.get("default")
    return out(name, kind) if output else inp(name, kind, default)


def _param_from_dict(spec: dict) -> ParamSpec:
    return ParamSpec(
        str(spec.get("name") or "param"),
        str(spec.get("label") or spec.get("name") or "Param"),
        str(spec.get("kind") or "text"),
        spec.get("default"),
        choices=tuple(spec.get("choices") or ()),
        description=str(spec.get("description") or ""),
        minimum=spec.get("minimum"),
        maximum=spec.get("maximum"),
    )


def build_script_node(manifest: PluginManifest, spec: PluginNodeSpec, runner=None):
    """Turn a manifest-declared script node into a registered definition.

    ``runner`` defaults to :func:`synapse.scripting.runner.run_script`; the
    code receives ``inputs`` and ``params`` and must set ``result``.
    """
    if not spec.code.strip():
        raise ValueError(f"script node '{spec.type_id}' has no code")
    if manifest.directory is None:
        raise ValueError("script plugins need a directory")
    async def execute(ctx, inputs, params):
        options = ScriptOptions(
            timeout=float(params.get("timeout") or 15.0),
            allowed_imports=("json", "math", "re", "datetime", "collections", "itertools", "statistics"),
            allow_all_imports=False,
            working_dir=str(manifest.directory),
        )
        result = (runner or run_script)(
            spec.code, dict(inputs), dict(params), options=options
        )
        value = result.result
        outputs = [str(o.get("name") or "result") for o in spec.outputs] or ["result"]
        if isinstance(value, dict) and outputs[0] in value:
            return value
        return {outputs[0]: value}

    return make_definition(
        f"ext.{manifest.name}.{spec.type_id}",
        spec.name,
        spec.category,
        description=spec.description,
        inputs=[_port_from_dict(p, output=False) for p in spec.inputs],
        outputs=[_port_from_dict(p, output=True) for p in spec.outputs] or [out("result", DataType.ANY)],
        params=[_param_from_dict(p) for p in spec.params],
        execute=execute,
        pure=spec.pure,
        extension=manifest.name,
    )
