"""Node definition primitives shared by builtin nodes, functions and plugins."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable, Iterable, Sequence

from ..typesystem import DataType, PortSpec, TypeSpec


NodeCallable = Callable[[Any, dict, dict], "dict | Awaitable[dict]"]


@dataclass(frozen=True)
class ParamSpec:
    """A configurable, non-port value on a node (edited in the inspector)."""

    name: str
    label: str = ""
    kind: str = "text"  # text | multiline | int | float | bool | choice | code | file | json
    default: Any = None
    choices: tuple[str, ...] = ()
    description: str = ""
    minimum: float | None = None
    maximum: float | None = None
    secret: bool = False

    def __post_init__(self) -> None:
        if not self.label:
            object.__setattr__(self, "label", self.name.replace("_", " ").title())

    def coerce(self, value: Any) -> Any:
        if self.kind == "int":
            return int(value)
        if self.kind == "float":
            return float(value)
        if self.kind == "bool":
            return bool(value)
        if self.kind == "json":
            return value
        if value is None:
            return ""
        return str(value)


@dataclass
class NodeDefinition:
    """Everything SYNAPSE needs to place, validate, execute and document a node."""

    type_id: str
    name: str
    category: str
    description: str = ""
    inputs: tuple[PortSpec, ...] = ()
    outputs: tuple[PortSpec, ...] = ()
    params: dict[str, ParamSpec] = field(default_factory=dict)
    version: int = 1
    pure: bool = True
    execute: NodeCallable | None = None
    keywords: tuple[str, ...] = ()
    blocking: bool = False
    free_params: bool = False
    default_width: float = 200.0
    default_height: float = 110.0
    source: str = "builtin"  # builtin | function | plugin
    extension: str | None = None
    codegen: str = "unsupported"  # python | unsupported
    dynamic: bool = False
    function_id: str | None = None

    # -- helpers --------------------------------------------------------
    def default_params(self) -> dict[str, Any]:
        return {name: spec.default for name, spec in self.params.items()}

    def resolve_inputs(self, graph, node) -> Sequence[PortSpec]:
        return self.inputs

    def resolve_outputs(self, graph, node) -> Sequence[PortSpec]:
        return self.outputs

    def port(self, name: str, *, output: bool) -> PortSpec | None:
        ports = self.outputs if output else self.inputs
        for port in ports:
            if port.name == name:
                return port
        return None

    def signature(self) -> str:
        ins = ", ".join(f"{p.name}: {p.spec}" for p in self.inputs)
        outs = ", ".join(f"{p.name}: {p.spec}" for p in self.outputs)
        return f"({ins}) -> ({outs})"

    async def invoke(self, ctx, inputs: dict, params: dict) -> dict:
        if self.execute is None:
            raise NotImplementedError(
                f"node type '{self.type_id}' has no execute implementation"
            )
        result = self.execute(ctx, inputs, params)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, dict):
            raise TypeError(
                f"node '{self.type_id}' returned {type(result).__name__}, expected dict"
            )
        unknown = set(result) - {p.name for p in self.outputs}
        if unknown and not self.dynamic:
            raise ValueError(
                f"node '{self.type_id}' produced unknown outputs: {sorted(unknown)}"
            )
        return result

    def with_overrides(self, **changes) -> "NodeDefinition":
        return replace(self, **changes)


def _port(raw: Any, *, is_input: bool) -> PortSpec:
    if isinstance(raw, PortSpec):
        return raw
    if isinstance(raw, str):
        return PortSpec(raw)
    if isinstance(raw, (tuple, list)):
        name = str(raw[0])
        if len(raw) == 1:
            return PortSpec(name)
        typ = raw[1]
        default = raw[2] if len(raw) > 2 else None
        optional = default is not None or (len(raw) > 3 and bool(raw[3]))
        return PortSpec(name, typ, default=default, optional=optional)
    raise TypeError(f"cannot build a port from {raw!r}")


def ports(items: Iterable[Any]) -> tuple[PortSpec, ...]:
    return tuple(_port(item, is_input=True) for item in items)


def node(
    type_id: str,
    name: str,
    category: str,
    *,
    description: str = "",
    inputs: Sequence[Any] = (),
    outputs: Sequence[Any] = (),
    params: Sequence[ParamSpec] = (),
    version: int = 1,
    pure: bool = True,
    keywords: Sequence[str] = (),
    blocking: bool = False,
    codegen: str = "unsupported",
    width: float | None = None,
    height: float | None = None,
    extension: str | None = None,
):
    """Decorator registering a node implementation.

    The decorated function is ``def f(ctx, inputs, params) -> dict`` (sync or
    async) and must return a dict keyed by output port name.
    """

    def wrap(fn: NodeCallable) -> NodeCallable:
        definition = NodeDefinition(
            type_id=type_id,
            name=name,
            category=category,
            description=description,
            inputs=ports(inputs),
            outputs=ports(outputs),
            params={p.name: p for p in params},
            version=version,
            pure=pure,
            execute=fn,
            keywords=tuple(keywords),
            blocking=blocking,
            codegen=codegen,
            default_width=width or 200.0,
            default_height=height or 110.0,
            extension=extension,
        )
        fn.definition = definition  # type: ignore[attr-defined]
        return fn

    return wrap


def make_definition(
    type_id: str,
    name: str,
    category: str,
    *,
    inputs: Sequence[Any] = (),
    outputs: Sequence[Any] = (),
    params: Sequence[ParamSpec] = (),
    description: str = "",
    execute: NodeCallable | None = None,
    pure: bool = True,
    codegen: str = "unsupported",
    extension: str | None = None,
    source: str = "plugin",
    dynamic: bool = False,
    function_id: str | None = None,
) -> NodeDefinition:
    """Build a definition without the decorator (plugins and functions)."""
    return NodeDefinition(
        type_id=type_id,
        name=name,
        category=category,
        description=description,
        inputs=ports(inputs),
        outputs=ports(outputs),
        params={p.name: p for p in params},
        execute=execute,
        pure=pure,
        codegen=codegen,
        extension=extension,
        source=source,
        dynamic=dynamic,
        function_id=function_id,
    )


# Convenient shorthands used across node modules.
_NO_DEFAULT = object()


def inp(name: str, typ: DataType | TypeSpec = DataType.ANY, default: Any = _NO_DEFAULT,
        description: str = "") -> PortSpec:
    """Declare an input port.

    Omitting ``default`` makes the port required; passing a default (including
    an explicit ``None``) makes it optional.
    """
    optional = default is not _NO_DEFAULT
    return PortSpec(
        name,
        typ,
        default=None if not optional else default,
        description=description,
        optional=optional,
    )


def out(name: str, typ: DataType | TypeSpec = DataType.ANY,
        description: str = "") -> PortSpec:
    return PortSpec(name, typ, description=description)
