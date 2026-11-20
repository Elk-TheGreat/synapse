"""Image nodes built on Pillow: load, resize, filter, colour, draw and export."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from ...typesystem import DataType, FileRef, Image
from ..base import ParamSpec, inp, node, out


def _image(value: Any, name: str = "image") -> Image:
    if isinstance(value, Image):
        return value
    if isinstance(value, (bytes, bytearray)):
        return Image.from_bytes(bytes(value))
    if isinstance(value, FileRef):
        value = value.path
    raise ValueError(f"'{name}' must be an image, got {type(value).__name__}")


def _load(path: str) -> Image:
    from PIL import Image as PILImage

    image = PILImage.open(path)
    image.load()
    return Image(image)


@node(
    "graphics.load",
    "Load Image",
    "Graphics",
    description="Loads a PNG/JPEG/WebP/BMP image from a file or bytes.",
    inputs=[inp("source", DataType.ANY)],
    outputs=[
        out("image", DataType.IMAGE),
        out("width", DataType.INTEGER),
        out("height", DataType.INTEGER),
        out("format", DataType.STRING),
    ],
    params=[],
    pure=False,
    blocking=True,
    keywords=("png", "jpg", "photo", "picture"),
)
async def load_image(ctx, inputs, params):
    source = inputs.get("source")
    if isinstance(source, (bytes, bytearray)):
        image = await ctx.run_blocking(Image.from_bytes, bytes(source))
        return {"image": image, "width": image.width, "height": image.height, "format": "bytes"}
    if isinstance(source, FileRef):
        source = source.path
    if source is None:
        raise ValueError("'source' input is empty")
    path = ctx.security.resolve_path(str(source))
    try:
        image = await ctx.run_blocking(_load, path)
    except Exception as exc:
        raise ValueError(f"cannot open image '{path}': {exc}") from exc
    return {
        "image": image,
        "width": image.width,
        "height": image.height,
        "format": Path(path).suffix.lstrip(".").lower() or "unknown",
    }


@node(
    "graphics.resize",
    "Resize Image",
    "Graphics",
    description="Resizes an image; a zero width or height keeps the aspect ratio.",
    inputs=[inp("image", DataType.IMAGE), inp("width", DataType.INTEGER, 0), inp("height", DataType.INTEGER, 0)],
    outputs=[out("image", DataType.IMAGE), out("width", DataType.INTEGER), out("height", DataType.INTEGER)],
    params=[
        ParamSpec("resample", "Resample", "choice", "lanczos", choices=("nearest", "bilinear", "bicubic", "lanczos")),
        ParamSpec("keep_aspect", "Keep aspect ratio", "bool", True),
    ],
    pure=False,
    blocking=True,
)
async def resize_image(ctx, inputs, params):
    from PIL import Image as PILImage

    image = _image(inputs.get("image"))
    width = int(inputs.get("width") or 0)
    height = int(inputs.get("height") or 0)
    if width <= 0 and height <= 0:
        raise ValueError("set a width or a height")
    if width <= 0:
        width = max(1, round(image.width * height / image.height))
    if height <= 0:
        height = max(1, round(image.height * width / image.width))
    if width > 20000 or height > 20000:
        raise ValueError("image dimensions are limited to 20000 pixels")
    resample = {
        "nearest": PILImage.NEAREST,
        "bilinear": PILImage.BILINEAR,
        "bicubic": PILImage.BICUBIC,
        "lanczos": PILImage.LANCZOS,
    }[str(params.get("resample") or "lanczos")]

    def work() -> tuple[Image, int, int]:
        resized = image.pil.resize((width, height), resample)
        return Image(resized), resized.width, resized.height

    result, w, h = await ctx.run_blocking(work)
    return {"image": result, "width": w, "height": h}


@node(
    "graphics.filter",
    "Image Filter",
    "Graphics",
    inputs=[inp("image", DataType.IMAGE)],
    outputs=[out("image", DataType.IMAGE)],
    params=[
        ParamSpec(
            "filter",
            "Filter",
            "choice",
            "grayscale",
            choices=("grayscale", "blur", "sharpen", "edge", "emboss", "invert", "posterize", "threshold", "smooth"),
        ),
        ParamSpec("amount", "Amount / threshold", "int", 16, minimum=0, maximum=255),
    ],
    pure=False,
    blocking=True,
)
async def filter_image(ctx, inputs, params):
    from PIL import ImageFilter, ImageOps

    image = _image(inputs.get("image"))
    name = str(params.get("filter") or "grayscale")
    amount = int(params.get("amount") or 0)

    def work() -> Image:
        pil = image.pil
        if name == "grayscale":
            return Image(ImageOps.grayscale(pil))
        if name == "invert":
            return Image(ImageOps.invert(pil.convert("RGB")))
        if name == "blur":
            return Image(pil.filter(ImageFilter.GaussianBlur(max(0.5, amount / 4 or 2))))
        if name == "sharpen":
            return Image(pil.filter(ImageFilter.SHARPEN))
        if name == "smooth":
            return Image(pil.filter(ImageFilter.SMOOTH_MORE))
        if name == "edge":
            return Image(pil.filter(ImageFilter.FIND_EDGES))
        if name == "emboss":
            return Image(pil.filter(ImageFilter.EMBOSS))
        if name == "posterize":
            return Image(ImageOps.posterize(pil.convert("RGB"), max(1, min(7, amount // 32 or 4))))
        if name == "threshold":
            gray = ImageOps.grayscale(pil)
            return Image(gray.point(lambda p: 255 if p >= amount else 0))
        raise ValueError(f"unknown filter '{name}'")

    return {"image": await ctx.run_blocking(work)}


@node(
    "graphics.color",
    "Colour Adjust",
    "Graphics",
    description="Adjusts brightness, contrast and saturation, or applies a tint.",
    inputs=[inp("image", DataType.IMAGE)],
    outputs=[out("image", DataType.IMAGE)],
    params=[
        ParamSpec("brightness", "Brightness", "float", 1.0, minimum=0.0, maximum=4.0),
        ParamSpec("contrast", "Contrast", "float", 1.0, minimum=0.0, maximum=4.0),
        ParamSpec("saturation", "Saturation", "float", 1.0, minimum=0.0, maximum=4.0),
        ParamSpec("tint", "Tint colour", "text", ""),
        ParamSpec("tint_strength", "Tint strength", "float", 0.0, minimum=0.0, maximum=1.0),
    ],
    pure=False,
    blocking=True,
)
async def colour_image(ctx, inputs, params):
    from PIL import ImageEnhance, ImageColor

    image = _image(inputs.get("image"))

    def work() -> Image:
        pil = image.pil.convert("RGB")
        pil = ImageEnhance.Brightness(pil).enhance(float(params.get("brightness") or 1.0))
        pil = ImageEnhance.Contrast(pil).enhance(float(params.get("contrast") or 1.0))
        pil = ImageEnhance.Color(pil).enhance(float(params.get("saturation") or 1.0))
        tint = str(params.get("tint") or "").strip()
        strength = float(params.get("tint_strength") or 0.0)
        if tint and strength > 0:
            try:
                rgb = ImageColor.getrgb(tint)
            except ValueError as exc:
                raise ValueError(f"invalid tint colour '{tint}'") from exc
            overlay = ImageEnhance.Brightness(pil).enhance(1.0)
            layer = overlay.pil.copy()
            solid = type(layer).new("RGB", layer.size, rgb)
            from PIL import Image as PILImage

            blended = PILImage.blend(layer, solid, min(1.0, strength))
            return Image(blended)
        return Image(pil)

    return {"image": await ctx.run_blocking(work)}


@node(
    "graphics.draw",
    "Draw",
    "Graphics",
    description="Draws rectangles, ellipses, lines and text described by a JSON list.",
    inputs=[inp("image", DataType.IMAGE, None)],
    outputs=[out("image", DataType.IMAGE), out("width", DataType.INTEGER), out("height", DataType.INTEGER)],
    params=[
        ParamSpec("width", "Canvas width", "int", 640, minimum=1, maximum=8000),
        ParamSpec("height", "Canvas height", "int", 480, minimum=1, maximum=8000),
        ParamSpec("background", "Background", "text", "#111827"),
        ParamSpec(
            "shapes",
            "Shapes (JSON)",
            "json",
            '[{"type": "rect", "xy": [40, 40, 200, 140], "fill": "#38bdf8"}]',
        ),
    ],
    pure=False,
    blocking=True,
)
async def draw(ctx, inputs, params):
    from PIL import Image as PILImage, ImageDraw, ImageFont

    raw = params.get("shapes")
    try:
        shapes = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except json.JSONDecodeError as exc:
        raise ValueError(f"'shapes' is not valid JSON: {exc}") from exc
    if not isinstance(shapes, list):
        raise ValueError("'shapes' must be a JSON array")
    source = inputs.get("image")

    def work() -> Image:
        if isinstance(source, Image):
            base = source.pil.convert("RGB").copy()
        else:
            base = PILImage.new(
                "RGB",
                (int(params.get("width") or 640), int(params.get("height") or 480)),
                str(params.get("background") or "#111827"),
            )
        canvas = ImageDraw.Draw(base)
        for index, shape in enumerate(shapes):
            if not isinstance(shape, dict):
                raise ValueError(f"shape {index} is not an object")
            kind = str(shape.get("type") or "rect")
            fill = shape.get("fill")
            outline = shape.get("outline")
            width = int(shape.get("width") or 1)
            if kind == "text":
                try:
                    font = ImageFont.truetype(str(shape.get("font") or "DejaVuSans.ttf"), int(shape.get("size") or 24))
                except OSError:
                    font = ImageFont.load_default()
                canvas.text(tuple(shape.get("xy") or (0, 0)), str(shape.get("text") or ""), fill=fill or "white", font=font)
                continue
            xy = shape.get("xy")
            if not isinstance(xy, list) or len(xy) < 2:
                raise ValueError(f"shape {index} needs an 'xy' list")
            if kind == "rect":
                canvas.rectangle(xy, fill=fill, outline=outline, width=width)
            elif kind == "ellipse":
                canvas.ellipse(xy, fill=fill, outline=outline, width=width)
            elif kind == "line":
                canvas.line(xy, fill=fill or outline or "white", width=max(1, width))
            elif kind == "polygon":
                canvas.polygon(xy, fill=fill, outline=outline)
            else:
                raise ValueError(f"unknown shape type '{kind}'")
        return Image(base)

    result = await ctx.run_blocking(work)
    return {"image": result, "width": result.width, "height": result.height}


@node(
    "graphics.crop",
    "Crop Image",
    "Graphics",
    inputs=[inp("image", DataType.IMAGE), inp("left", DataType.INTEGER, 0), inp("top", DataType.INTEGER, 0), inp("right", DataType.INTEGER, None), inp("bottom", DataType.INTEGER, None)],
    outputs=[out("image", DataType.IMAGE), out("width", DataType.INTEGER), out("height", DataType.INTEGER)],
    pure=False,
    blocking=True,
)
async def crop_image(ctx, inputs, params):
    image = _image(inputs.get("image"))
    left = int(inputs.get("left") or 0)
    top = int(inputs.get("top") or 0)
    right = int(inputs.get("right") or image.width)
    bottom = int(inputs.get("bottom") or image.height)
    if not (0 <= left < right <= image.width and 0 <= top < bottom <= image.height):
        raise ValueError(
            f"crop box ({left}, {top}, {right}, {bottom}) is outside the {image.width}x{image.height} image"
        )
    result = await ctx.run_blocking(lambda: Image(image.pil.crop((left, top, right, bottom))))
    return {"image": result, "width": result.width, "height": result.height}


@node(
    "graphics.export",
    "Export Image",
    "Graphics",
    description="Saves an image to a file inside the project folder.",
    inputs=[inp("image", DataType.IMAGE), inp("path", DataType.ANY)],
    outputs=[out("path", DataType.ANY), out("size", DataType.INTEGER), out("format", DataType.STRING)],
    params=[
        ParamSpec("format", "Format", "choice", "png", choices=("png", "jpeg", "webp", "bmp")),
        ParamSpec("quality", "Quality (JPEG/WebP)", "int", 90, minimum=1, maximum=100),
    ],
    pure=False,
    blocking=True,
    keywords=("save", "write", "png", "jpg"),
)
async def export_image(ctx, inputs, params):
    image = _image(inputs.get("image"))
    path = ctx.security.resolve_path(str(inputs.get("path") or "output.png"), write=True)
    fmt = str(params.get("format") or "png").upper()
    quality = int(params.get("quality") or 90)

    def work() -> int:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        pil = image.pil
        if fmt == "JPEG":
            pil = pil.convert("RGB")
        pil.save(path, format=fmt, quality=quality, optimize=fmt in ("PNG", "JPEG"))
        return Path(path).stat().st_size

    size = await ctx.run_blocking(work)
    ctx.log(f"exported image to {path} ({size} bytes)", "info")
    return {"path": FileRef(path), "size": size, "format": fmt.lower()}


@node(
    "graphics.to_bytes",
    "Image To Bytes",
    "Graphics",
    inputs=[inp("image", DataType.IMAGE)],
    outputs=[out("bytes", DataType.BYTES), out("base64", DataType.STRING)],
    params=[ParamSpec("format", "Format", "choice", "PNG", choices=("PNG", "JPEG", "WEBP"))],
    pure=False,
    blocking=True,
)
async def image_to_bytes(ctx, inputs, params):
    import base64 as b64

    image = _image(inputs.get("image"))
    raw = await ctx.run_blocking(image.to_bytes, str(params.get("format") or "PNG"))
    return {"bytes": raw, "base64": b64.b64encode(raw).decode("ascii")}


@node(
    "graphics.from_bytes",
    "Image From Bytes",
    "Graphics",
    inputs=[inp("data", DataType.BYTES)],
    outputs=[out("image", DataType.IMAGE), out("width", DataType.INTEGER), out("height", DataType.INTEGER)],
    pure=False,
    blocking=True,
)
async def image_from_bytes(ctx, inputs, params):
    raw = inputs.get("data")
    if not isinstance(raw, (bytes, bytearray)):
        raise ValueError("'data' must be bytes")
    image = await ctx.run_blocking(Image.from_bytes, bytes(raw))
    return {"image": image, "width": image.width, "height": image.height}


@node(
    "graphics.pixel",
    "Get Pixel",
    "Graphics",
    inputs=[inp("image", DataType.IMAGE), inp("x", DataType.INTEGER), inp("y", DataType.INTEGER)],
    outputs=[out("color", DataType.ARRAY), out("hex", DataType.STRING)],
    pure=False,
    blocking=True,
)
async def get_pixel(ctx, inputs, params):
    image = _image(inputs.get("image"))
    x, y = int(inputs.get("x") or 0), int(inputs.get("y") or 0)
    if not (0 <= x < image.width and 0 <= y < image.height):
        raise ValueError(f"pixel ({x}, {y}) is outside the {image.width}x{image.height} image")
    pixel = await ctx.run_blocking(lambda: image.pil.convert("RGB").getpixel((x, y)))
    return {"color": list(pixel), "hex": "#{:02x}{:02x}{:02x}".format(*pixel)}
