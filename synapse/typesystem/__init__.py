"""SYNAPSE type system."""

from .media import Audio, FileRef, Image, Video
from .types import (
    ANY,
    NUMERIC,
    ConversionError,
    CustomType,
    DataType,
    PortSpec,
    TypeSpec,
    coerce_value,
    compatibility_error,
    custom_type,
    custom_types,
    infer_type,
    is_compatible,
    register_custom_type,
    type_label,
    unregister_custom_type,
)

__all__ = [
    "ANY",
    "Audio",
    "FileRef",
    "Image",
    "Video",
    "NUMERIC",
    "ConversionError",
    "CustomType",
    "DataType",
    "PortSpec",
    "TypeSpec",
    "coerce_value",
    "compatibility_error",
    "custom_type",
    "custom_types",
    "infer_type",
    "is_compatible",
    "register_custom_type",
    "type_label",
    "unregister_custom_type",
]
