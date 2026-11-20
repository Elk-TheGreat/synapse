"""Minimal RFC 6455 WebSocket client used by the WebSocket node.

Only what the node needs is implemented: handshake, one text/binary exchange
and a clean close.  It is deliberately small instead of pulling in a dependency.
"""

from __future__ import annotations

import asyncio
import base64
import os
import struct
from urllib.parse import urlparse


class WebSocketError(RuntimeError):
    pass


def _frame(payload: bytes, opcode: int = 0x1) -> bytes:
    mask = os.urandom(4)
    header = bytearray([0x80 | opcode])
    length = len(payload)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header += struct.pack("!H", length)
    else:
        header.append(0x80 | 127)
        header += struct.pack("!Q", length)
    header += mask
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return bytes(header) + masked


async def _read_frame(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    first = await reader.readexactly(2)
    opcode = first[0] & 0x0F
    masked = bool(first[1] & 0x80)
    length = first[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", await reader.readexactly(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", await reader.readexactly(8))[0]
    if length > 32 * 1024 * 1024:
        raise WebSocketError("frame is larger than 32 MiB")
    mask = await reader.readexactly(4) if masked else b""
    payload = await reader.readexactly(length)
    if mask:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return opcode, payload


async def exchange(
    url: str,
    message: str | bytes | None,
    *,
    timeout: float = 15.0,
    headers: dict[str, str] | None = None,
    max_messages: int = 1,
) -> list[str]:
    """Connect, send ``message`` (if any), collect up to ``max_messages`` replies."""
    parsed = urlparse(url)
    if parsed.scheme not in ("ws", "wss"):
        raise WebSocketError("WebSocket URLs must start with ws:// or wss://")
    if not parsed.hostname:
        raise WebSocketError(f"'{url}' has no host")
    secure = parsed.scheme == "wss"
    port = parsed.port or (443 if secure else 80)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query

    ssl_context = None
    if secure:
        import ssl

        ssl_context = ssl.create_default_context()

    async def run() -> list[str]:
        reader, writer = await asyncio.open_connection(
            parsed.hostname, port, ssl=ssl_context, server_hostname=parsed.hostname if secure else None
        )
        try:
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            request = [
                f"GET {path} HTTP/1.1",
                f"Host: {parsed.netloc}",
                "Upgrade: websocket",
                "Connection: Upgrade",
                f"Sec-WebSocket-Key: {key}",
                "Sec-WebSocket-Version: 13",
            ]
            for name, value in (headers or {}).items():
                request.append(f"{name}: {value}")
            writer.write(("\r\n".join(request) + "\r\n\r\n").encode("latin-1"))
            await writer.drain()
            status_line = await reader.readline()
            if b"101" not in status_line:
                raise WebSocketError(f"handshake refused: {status_line.decode('latin-1').strip()}")
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
            if message is not None:
                opcode = 0x2 if isinstance(message, (bytes, bytearray)) else 0x1
                payload = bytes(message) if opcode == 0x2 else str(message).encode("utf-8")
                writer.write(_frame(payload, opcode))
                await writer.drain()
            replies: list[str] = []
            while len(replies) < max_messages:
                opcode, payload = await _read_frame(reader)
                if opcode == 0x8:
                    break
                if opcode == 0x9:  # ping
                    writer.write(_frame(payload, 0xA))
                    await writer.drain()
                    continue
                if opcode == 0xA:
                    continue
                replies.append(payload.decode("utf-8", "replace"))
            writer.write(_frame(b"", 0x8))
            await writer.drain()
            return replies
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    try:
        return await asyncio.wait_for(run(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise WebSocketError(f"WebSocket exchange timed out after {timeout:g}s") from exc
    except (OSError, asyncio.IncompleteReadError) as exc:
        raise WebSocketError(f"WebSocket connection failed: {exc}") from exc
