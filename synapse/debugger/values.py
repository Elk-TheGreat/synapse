"""Human readable and JSON-safe rendering of runtime values."""

from __future__ import annotations

import base64
import json
import pprint
from typing import Any

MAX_PREVIEW = 160


def truncate(text: str, limit: int = MAX_PREVIEW) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def value_preview(value: Any) -> str:
    """One-line summary used on wires and in tables."""
    from ..typesystem import media

    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        text = value.replace("\n", "\\n")
        return truncate(f'"{text}"')
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    if isinstance(value, list):
        inner = ", ".join(value_preview(v) for v in value[:4])
        if len(value) > 4:
            inner += f", … ({len(value)} items)"
        return truncate(f"[{inner}]")
    if isinstance(value, dict):
        inner = ", ".join(f"{k}: {value_preview(v)}" for k, v in list(value.items())[:3])
        if len(value) > 3:
            inner += ", …"
        return truncate("{" + inner + "}")
    if isinstance(value, media.Image):
        return f"<image {value.width}x{value.height} {value.mode}>"
    if isinstance(value, media.Audio):
        return f"<audio {len(value.data)} bytes>"
    if isinstance(value, media.Video):
        return f"<video {value.path}>"
    if isinstance(value, media.FileRef):
        return f"<file {value.path}>"
    return truncate(repr(value))


def format_value(value: Any, limit: int = 4000) -> str:
    """Multi-line inspector form."""
    try:
        text = pprint.pformat(value, width=88, sort_dicts=False)
    except Exception:  # pragma: no cover - exotic objects
        text = repr(value)
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


def to_jsonable(value: Any, depth: int = 0) -> Any:
    """Best-effort conversion for the console, history and JSON export."""
    from ..typesystem import media

    if depth > 8:
        return "<max depth>"
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return {"__type__": "bytes", "base64": base64.b64encode(bytes(value)).decode()}
    if isinstance(value, media.Image):
        return {
            "__type__": "image",
            "width": value.width,
            "height": value.height,
            "mode": value.mode,
        }
    if isinstance(value, media.Audio):
        return {"__type__": "audio", "bytes": len(value.data), "duration": value.duration}
    if isinstance(value, media.Video):
        return {"__type__": "video", "path": value.path}
    if isinstance(value, media.FileRef):
        return {"__type__": "file", "path": value.path}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v, depth + 1) for v in value]
    if isinstance(value, dict):
        return {str(k): to_jsonable(v, depth + 1) for k, v in value.items()}
    try:
        json.dumps(value)
        return value
    except Exception:
        return repr(value)
