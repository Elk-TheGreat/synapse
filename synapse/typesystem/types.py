"""SYNAPSE type system.

Values are represented with native Python objects; media values are wrapped in
small dataclasses so they can be typed and inspected uniformly.

    boolean    -> bool
    integer    -> int
    float      -> float
    string     -> str
    bytes      -> bytes / bytearray
    array      -> list
    dictionary -> dict
    image      -> synapse.typesystem.media.Image
    audio      -> synapse.typesystem.media.Audio
    video      -> synapse.typesystem.media.Video
    file       -> synapse.typesystem.media.FileRef
    object     -> anything else (or a registered custom type)
    any        -> no static type; checked at runtime
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any as TAny


class DataType(str, Enum):
    BOOLEAN = "boolean"
    INTEGER = "integer"
    FLOAT = "float"
    STRING = "string"
    BYTES = "bytes"
    ARRAY = "array"
    DICTIONARY = "dictionary"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    FILE = "file"
    OBJECT = "object"
    ANY = "any"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


NUMERIC = (DataType.INTEGER, DataType.FLOAT)


class ConversionError(TypeError):
    """Raised when a value cannot be turned into the requested type."""


@dataclass(frozen=True)
class TypeSpec:
    """A declared port type: a base type plus optional custom type name."""

    type: DataType = DataType.ANY
    type_name: str | None = None
    element: "TypeSpec | None" = None

    @classmethod
    def of(cls, value: "DataType | TypeSpec | str") -> "TypeSpec":
        if isinstance(value, TypeSpec):
            return value
        return cls(DataType(value))

    def __str__(self) -> str:
        if self.type is DataType.ARRAY and self.element is not None:
            return f"array<{self.element}>"
        if self.type_name:
            return self.type_name
        return self.type.value


ANY = TypeSpec(DataType.ANY)


@dataclass(frozen=True)
class PortSpec:
    """Describes one input or output port of a node."""

    name: str
    type: "DataType | TypeSpec" = DataType.ANY
    description: str = ""
    optional: bool = False
    default: TAny = None
    variadic: bool = False

    @property
    def spec(self) -> TypeSpec:
        return TypeSpec.of(self.type)

    @property
    def data_type(self) -> DataType:
        return self.spec.type

    def to_dict(self) -> dict:
        d: dict = {
            "name": self.name,
            "type": self.spec.type.value,
            "description": self.description,
            "optional": self.optional,
        }
        if self.spec.type_name:
            d["type_name"] = self.spec.type_name
        if self.spec.element is not None:
            d["element"] = self.spec.element.type.value
        if self.default is not None:
            d["default"] = self.default
        if self.variadic:
            d["variadic"] = True
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "PortSpec":
        spec = TypeSpec(DataType(data.get("type", "any")), data.get("type_name"))
        element = data.get("element")
        if element:
            spec = TypeSpec(spec.type, spec.type_name, TypeSpec.of(element))
        return cls(
            name=str(data["name"]),
            type=spec,
            description=str(data.get("description", "")),
            optional=bool(data.get("optional", False)),
            default=data.get("default"),
            variadic=bool(data.get("variadic", False)),
        )


# --------------------------------------------------------------------------
# Custom named types
# --------------------------------------------------------------------------

@dataclass
class CustomType:
    """A named object type with an optional validator."""

    name: str
    description: str = ""
    fields: dict[str, TypeSpec] = field(default_factory=dict)

    def validate(self, value: TAny) -> None:
        if not isinstance(value, dict):
            raise ConversionError(
                f"value for custom type '{self.name}' must be a dictionary, "
                f"got {type(value).__name__}"
            )
        for field_name, spec in self.fields.items():
            if field_name not in value:
                raise ConversionError(
                    f"custom type '{self.name}' is missing field '{field_name}'"
                )
            coerce_value(value[field_name], spec)


_custom_types: dict[str, CustomType] = {}


def register_custom_type(custom: CustomType, *, replace: bool = False) -> CustomType:
    if custom.name in _custom_types and not replace:
        raise ValueError(f"custom type '{custom.name}' is already registered")
    _custom_types[custom.name] = custom
    return custom


def unregister_custom_type(name: str) -> None:
    _custom_types.pop(name, None)


def custom_type(name: str) -> CustomType | None:
    return _custom_types.get(name)


def custom_types() -> dict[str, CustomType]:
    return dict(_custom_types)


# --------------------------------------------------------------------------
# Connection compatibility
# --------------------------------------------------------------------------

def is_compatible(source: "DataType | TypeSpec", target: "DataType | TypeSpec") -> bool:
    """Can an output of ``source`` be wired into an input of ``target``?

    Widening numeric conversions and bool->integer are implicit. Everything
    else needs an explicit conversion node (e.g. "Data > To string").
    """
    s, t = TypeSpec.of(source), TypeSpec.of(target)
    if s.type is DataType.ANY or t.type is DataType.ANY:
        return True
    if s == t:
        return True
    if s.type_name and t.type_name:
        return s.type_name == t.type_name
    if t.type is DataType.OBJECT:
        return True
    if s.type is DataType.INTEGER and t.type in (DataType.FLOAT, DataType.STRING):
        return True
    if s.type is DataType.FLOAT and t.type is DataType.STRING:
        return True
    if s.type is DataType.BOOLEAN and t.type in (DataType.INTEGER, DataType.STRING):
        return True
    if s.type is DataType.BYTES and t.type is DataType.STRING:
        return True
    if s.type is DataType.STRING and t.type is DataType.BYTES:
        return True
    if s.type is DataType.FILE and t.type is DataType.STRING:
        return True
    if s.type is DataType.IMAGE and t.type in (DataType.BYTES,):
        return True
    if s.type is DataType.ARRAY and t.type is DataType.ARRAY:
        if s.element is None or t.element is None:
            return True
        return is_compatible(s.element, t.element)
    return False


def compatibility_error(source: "DataType | TypeSpec", target: "DataType | TypeSpec") -> str:
    return (
        f"incompatible types: cannot connect {TypeSpec.of(source)} output to "
        f"{TypeSpec.of(target)} input"
    )


# --------------------------------------------------------------------------
# Runtime coercion
# --------------------------------------------------------------------------

def _describe(value: TAny) -> str:
    return type(value).__name__


def infer_type(value: TAny) -> DataType:
    from . import media

    if value is None:
        return DataType.ANY
    if isinstance(value, bool):
        return DataType.BOOLEAN
    if isinstance(value, int):
        return DataType.INTEGER
    if isinstance(value, float):
        return DataType.FLOAT
    if isinstance(value, str):
        return DataType.STRING
    if isinstance(value, (bytes, bytearray, memoryview)):
        return DataType.BYTES
    if isinstance(value, list):
        return DataType.ARRAY
    if isinstance(value, dict):
        return DataType.DICTIONARY
    if isinstance(value, media.Image):
        return DataType.IMAGE
    if isinstance(value, media.Audio):
        return DataType.AUDIO
    if isinstance(value, media.Video):
        return DataType.VIDEO
    if isinstance(value, media.FileRef):
        return DataType.FILE
    return DataType.OBJECT


def coerce_value(value: TAny, target: "DataType | TypeSpec", *, port: str = "") -> TAny:
    """Convert ``value`` to ``target`` or raise ConversionError.

    ``None`` is accepted for any target: a missing value is represented as
    null and nodes either have a default for it or raise their own error.
    """
    spec = TypeSpec.of(target)
    if value is None:
        return None
    if spec.type is DataType.ANY:
        return value
    from . import media

    actual = infer_type(value)
    where = f" for port '{port}'" if port else ""

    if spec.type_name:
        custom = custom_type(spec.type_name)
        if custom is None:
            raise ConversionError(f"unknown custom type '{spec.type_name}'{where}")
        try:
            custom.validate(value)
        except ConversionError as exc:
            raise ConversionError(str(exc) + where) from exc
        return value

    if actual is spec.type:
        if spec.type is DataType.ARRAY and spec.element is not None:
            return [coerce_value(v, spec.element, port=port) for v in value]
        return value
    if spec.type is DataType.OBJECT:
        return value

    try:
        if spec.type is DataType.STRING:
            if isinstance(value, (bytes, bytearray)):
                return bytes(value).decode("utf-8", errors="replace")
            if isinstance(value, media.FileRef):
                return str(value.path)
            if isinstance(value, bool):
                return "true" if value else "false"
            if isinstance(value, (list, dict, tuple)):
                raise ConversionError(
                    f"cannot convert {_describe(value)} to string{where}; "
                    "use the JSON or serialisation nodes"
                )
            return str(value)
        if spec.type is DataType.INTEGER:
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, float):
                if value != int(value):
                    raise ConversionError(
                        f"cannot safely convert {value!r} to integer (lossy){where}"
                    )
                return int(value)
            if isinstance(value, str):
                return int(value.strip())
        if spec.type is DataType.FLOAT:
            if isinstance(value, (bool, int)):
                return float(value)
            if isinstance(value, str):
                return float(value.strip())
        if spec.type is DataType.BOOLEAN:
            if isinstance(value, (int, float)):
                return bool(value)
            if isinstance(value, str):
                low = value.strip().lower()
                if low in ("true", "1", "yes", "on"):
                    return True
                if low in ("false", "0", "no", "off", ""):
                    return False
                raise ConversionError(f"cannot convert {value!r} to boolean{where}")
        if spec.type is DataType.BYTES:
            if isinstance(value, str):
                return value.encode("utf-8")
            if isinstance(value, media.Image):
                return value.to_bytes()
        if spec.type is DataType.ARRAY:
            if isinstance(value, (list, tuple)):
                out = list(value)
                if spec.element is not None:
                    out = [coerce_value(v, spec.element, port=port) for v in out]
                return out
            raise ConversionError(
                f"cannot convert {_describe(value)} to array{where}"
            )
        if spec.type is DataType.DICTIONARY:
            if isinstance(value, dict):
                return dict(value)
            raise ConversionError(
                f"cannot convert {_describe(value)} to dictionary{where}"
            )
        if spec.type is DataType.FILE:
            if isinstance(value, str):
                return media.FileRef(value)
            if isinstance(value, media.FileRef):
                return value
        if spec.type in (DataType.IMAGE, DataType.AUDIO, DataType.VIDEO):
            raise ConversionError(
                f"cannot convert {_describe(value)} to {spec.type.value}{where}; "
                "use the matching media node"
            )
    except ConversionError:
        raise
    except (TypeError, ValueError) as exc:
        raise ConversionError(
            f"cannot convert {value!r} ({_describe(value)}) to {spec.type.value}{where}: {exc}"
        ) from exc

    raise ConversionError(
        f"cannot convert {_describe(value)} to {spec.type.value}{where}"
    )


def type_label(value: TAny) -> str:
    if value is None:
        return "null"
    from . import media

    if isinstance(value, media.Image):
        return f"image {value.width}x{value.height}"
    if isinstance(value, media.Audio):
        return f"audio {value.duration:.2f}s"
    if isinstance(value, media.Video):
        return f"video {value.path or 'memory'}"
    if isinstance(value, media.FileRef):
        return f"file {value.name}"
    return infer_type(value).value
