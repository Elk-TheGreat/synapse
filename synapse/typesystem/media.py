"""Media value wrappers used by the graphics, audio and file nodes."""

from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class FileRef:
    """A path on disk plus its resolved name."""

    path: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", os.fspath(self.path))

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def suffix(self) -> str:
        return Path(self.path).suffix.lower()

    def exists(self) -> bool:
        return os.path.exists(self.path)

    def __str__(self) -> str:
        return self.path


class Image:
    """A raster image backed by Pillow."""

    def __init__(self, pil_image) -> None:
        from PIL import Image as PILImage

        if not isinstance(pil_image, PILImage.Image):
            raise TypeError("Image() expects a PIL.Image.Image instance")
        self._image = pil_image

    @property
    def pil(self):
        return self._image

    @property
    def width(self) -> int:
        return self._image.width

    @property
    def height(self) -> int:
        return self._image.height

    @property
    def mode(self) -> str:
        return self._image.mode

    def to_bytes(self, fmt: str = "PNG") -> bytes:
        buf = io.BytesIO()
        self._image.save(buf, format=fmt)
        return buf.getvalue()

    @classmethod
    def from_bytes(cls, data: bytes) -> "Image":
        from PIL import Image as PILImage

        return cls(PILImage.open(io.BytesIO(data)))

    @classmethod
    def open(cls, path: str) -> "Image":
        from PIL import Image as PILImage

        return cls(PILImage.open(os.fspath(path)))

    def save(self, path: str, fmt: str | None = None) -> str:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._image.save(path, format=fmt)
        return path

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"Image({self.width}x{self.height}, {self.mode})"


@dataclass
class Audio:
    """PCM/compressed audio payload held in memory."""

    data: bytes
    sample_rate: int = 44100
    channels: int = 1
    fmt: str = "wav"

    @property
    def duration(self) -> float:
        if self.fmt != "wav" or self.channels <= 0 or self.sample_rate <= 0:
            return 0.0
        # 44 byte canonical WAV header.
        return max(0, len(self.data) - 44) / (self.sample_rate * self.channels * 2)

    def save(self, path: str) -> str:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(self.data)
        return path


@dataclass
class Video:
    """A video file reference (SYNAPSE does not decode video itself)."""

    path: str
    duration: float = 0.0

    def exists(self) -> bool:
        return os.path.exists(self.path)
