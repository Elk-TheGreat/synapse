"""Networking nodes: HTTP, WebSocket, TCP, downloads and uploads.

Every request goes through ``SecurityPolicy.check_network`` so a project can
disable networking or restrict it to an allow-list of hosts.
"""

from __future__ import annotations

import asyncio
import base64
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from ...typesystem import DataType, FileRef
from ..base import ParamSpec, inp, node, out
from .wsclient import WebSocketError, exchange

USER_AGENT = "Synapse/1.0 (+https://github.com/)"


def _headers(raw: Any) -> dict[str, str]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError as exc:
        raise ValueError(f"headers are not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("headers must be a JSON object")
    return {str(k): str(v) for k, v in parsed.items()}


def _request(
    method: str,
    url: str,
    *,
    data: bytes | None,
    headers: dict[str, str],
    timeout: float,
    max_bytes: int,
) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, data=data, method=method.upper())
    request.add_header("User-Agent", USER_AGENT)
    for name, value in headers.items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise ValueError(f"response is larger than the {max_bytes} byte limit")
            return response.status, dict(response.headers), body
    except urllib.error.HTTPError as exc:
        body = exc.read(max_bytes) if exc.fp else b""
        return exc.code, dict(exc.headers or {}), body
    except urllib.error.URLError as exc:
        raise ConnectionError(f"request to {url} failed: {exc.reason}") from exc


def _prepare_body(body: Any, payload: Any, content_type: str) -> tuple[bytes | None, str]:
    if payload is not None:
        if isinstance(payload, (dict, list)):
            return json.dumps(payload).encode("utf-8"), content_type or "application/json"
        if isinstance(payload, bytes):
            return payload, content_type or "application/octet-stream"
        return str(payload).encode("utf-8"), content_type or "text/plain; charset=utf-8"
    if body in (None, ""):
        return None, content_type
    if isinstance(body, bytes):
        return body, content_type or "application/octet-stream"
    return str(body).encode("utf-8"), content_type


@node(
    "net.http_request",
    "HTTP Request",
    "Networking",
    description="Performs an HTTP request and returns the response body, status and headers.",
    inputs=[
        inp("url", DataType.STRING),
        inp("body", DataType.ANY, None),
        inp("payload", DataType.ANY, None),
        inp("headers", DataType.ANY, None),
    ],
    outputs=[
        out("status", DataType.INTEGER),
        out("text", DataType.STRING),
        out("json", DataType.ANY),
        out("headers", DataType.DICTIONARY),
        out("ok", DataType.BOOLEAN),
    ],
    params=[
        ParamSpec("method", "Method", "choice", "GET", choices=("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD")),
        ParamSpec("content_type", "Content-Type", "text", ""),
        ParamSpec("timeout", "Timeout (s)", "float", 20.0),
        ParamSpec("max_bytes", "Max response bytes", "int", 2_000_000, minimum=1),
    ],
    pure=False,
    blocking=True,
    keywords=("rest", "get", "post", "api", "fetch"),
)
async def http_request(ctx, inputs, params):
    url = str(inputs.get("url") or "").strip()
    if not url:
        raise ValueError("'url' input is empty")
    ctx.security.check_network(url)
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("HTTP Request accepts only http:// and https:// URLs")
    data, content_type = _prepare_body(inputs.get("body"), inputs.get("payload"), str(params.get("content_type") or ""))
    headers = _headers(inputs.get("headers"))
    if content_type and "content-type" not in {k.lower() for k in headers}:
        headers["Content-Type"] = content_type
    timeout = float(params.get("timeout") or ctx.security.network_timeout)
    max_bytes = int(params.get("max_bytes") or 2_000_000)
    status, response_headers, raw = await ctx.run_blocking(
        _request,
        str(params.get("method") or "GET"),
        url,
        data=data,
        headers=headers,
        timeout=timeout,
        max_bytes=max_bytes,
    )
    text = raw.decode("utf-8", "replace")
    parsed: Any = None
    if "json" in response_headers.get("Content-Type", "") or text[:1] in ("{", "["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
    return {
        "status": status,
        "text": text,
        "json": parsed,
        "headers": {k: v for k, v in response_headers.items()},
        "ok": 200 <= status < 300,
    }


@node(
    "net.json_api",
    "JSON API",
    "Networking",
    description="Calls a JSON API and returns the parsed result; fails on HTTP errors.",
    inputs=[
        inp("url", DataType.STRING),
        inp("payload", DataType.ANY, None),
        inp("query", DataType.DICTIONARY, None),
        inp("headers", DataType.ANY, None),
    ],
    outputs=[out("data", DataType.ANY), out("status", DataType.INTEGER), out("headers", DataType.DICTIONARY)],
    params=[
        ParamSpec("method", "Method", "choice", "GET", choices=("GET", "POST", "PUT", "PATCH", "DELETE")),
        ParamSpec("timeout", "Timeout (s)", "float", 20.0),
    ],
    pure=False,
    blocking=True,
    keywords=("api", "rest", "json"),
)
async def json_api(ctx, inputs, params):
    base = str(inputs.get("url") or "").strip()
    if not base:
        raise ValueError("'url' input is empty")
    query = inputs.get("query")
    if isinstance(query, dict) and query:
        base += ("&" if "?" in base else "?") + urllib.parse.urlencode(query, doseq=True)
    ctx.security.check_network(base)
    if not base.lower().startswith(("http://", "https://")):
        raise ValueError("JSON API accepts only http:// and https:// URLs")
    method = str(params.get("method") or "GET").upper()
    payload = inputs.get("payload")
    headers = _headers(inputs.get("headers"))
    headers.setdefault("Accept", "application/json")
    data, content_type = _prepare_body(None, payload, "application/json")
    if data is not None and content_type:
        headers.setdefault("Content-Type", content_type)
    status, response_headers, raw = await ctx.run_blocking(
        _request,
        method,
        base,
        data=data,
        headers=headers,
        timeout=float(params.get("timeout") or ctx.security.network_timeout),
        max_bytes=8_000_000,
    )
    if status >= 400:
        raise ConnectionError(f"{method} {base} returned HTTP {status}: {raw[:300].decode('utf-8', 'replace')}")
    if not raw.strip():
        return {"data": None, "status": status, "headers": dict(response_headers)}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"response is not JSON: {exc}") from exc
    return {"data": parsed, "status": status, "headers": dict(response_headers)}


@node(
    "net.download",
    "Download",
    "Networking",
    description="Downloads a URL into a file inside the project folder.",
    inputs=[inp("url", DataType.STRING), inp("path", DataType.ANY)],
    outputs=[out("path", DataType.ANY), out("size", DataType.INTEGER)],
    params=[ParamSpec("timeout", "Timeout (s)", "float", 30.0)],
    pure=False,
    blocking=True,
    keywords=("save", "fetch", "file"),
)
async def download(ctx, inputs, params):
    url = str(inputs.get("url") or "").strip()
    if not url:
        raise ValueError("'url' input is empty")
    ctx.security.check_network(url)
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("Download accepts only http:// and https:// URLs")
    target = ctx.security.resolve_path(str(inputs.get("path") or ""), write=True)

    def fetch() -> int:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=float(params.get("timeout") or 30.0)) as response:
            expected = int(response.headers.get("Content-Length") or 0)
            limit = ctx.security.max_download_bytes
            if expected > limit:
                raise ValueError(f"download is {expected} bytes, above the {limit} byte limit")
            Path(target).parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with open(target, "wb") as handle:
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > limit:
                        raise ValueError(f"download exceeded the {limit} byte limit")
                    handle.write(chunk)
            return written

    try:
        size = await ctx.run_blocking(fetch)
    except urllib.error.HTTPError as exc:
        raise ConnectionError(f"download failed with HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ConnectionError(f"download failed: {exc.reason}") from exc
    return {"path": FileRef(target), "size": size}


@node(
    "net.upload",
    "Upload",
    "Networking",
    description="Uploads a file or text body to a URL with PUT or POST.",
    inputs=[inp("url", DataType.STRING), inp("file", DataType.ANY, None), inp("body", DataType.ANY, None), inp("headers", DataType.ANY, None)],
    outputs=[out("status", DataType.INTEGER), out("text", DataType.STRING), out("ok", DataType.BOOLEAN)],
    params=[
        ParamSpec("method", "Method", "choice", "PUT", choices=("PUT", "POST", "PATCH")),
        ParamSpec("content_type", "Content-Type", "text", "application/octet-stream"),
        ParamSpec("timeout", "Timeout (s)", "float", 60.0),
    ],
    pure=False,
    blocking=True,
)
async def upload(ctx, inputs, params):
    url = str(inputs.get("url") or "").strip()
    if not url:
        raise ValueError("'url' input is empty")
    ctx.security.check_network(url)
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("Upload accepts only http:// and https:// URLs")
    file_value = inputs.get("file")
    data: bytes | None = None
    if file_value is not None:
        source = str(file_value.path if isinstance(file_value, FileRef) else file_value)
        path = ctx.security.resolve_path(source)
        data = await ctx.run_blocking(Path(path).read_bytes)
    elif inputs.get("body") is not None:
        body = inputs.get("body")
        data = body if isinstance(body, bytes) else str(body).encode("utf-8")
    if data is None:
        raise ValueError("Upload needs a file or a body")
    headers = _headers(inputs.get("headers"))
    headers.setdefault("Content-Type", str(params.get("content_type") or "application/octet-stream"))
    status, response_headers, raw = await ctx.run_blocking(
        _request,
        str(params.get("method") or "PUT"),
        url,
        data=data,
        headers=headers,
        timeout=float(params.get("timeout") or 60.0),
        max_bytes=2_000_000,
    )
    return {"status": status, "text": raw.decode("utf-8", "replace"), "ok": 200 <= status < 300}


@node(
    "net.websocket",
    "WebSocket",
    "Networking",
    description="Opens a WebSocket, sends a message and returns the next replies (RFC 6455).",
    inputs=[inp("url", DataType.STRING), inp("message", DataType.ANY, None), inp("headers", DataType.ANY, None)],
    outputs=[out("messages", DataType.ARRAY), out("message", DataType.STRING), out("count", DataType.INTEGER)],
    params=[
        ParamSpec("timeout", "Timeout (s)", "float", 15.0),
        ParamSpec("max_messages", "Max messages", "int", 1, minimum=1, maximum=100),
    ],
    pure=False,
    keywords=("ws", "socket", "realtime"),
)
async def websocket(ctx, inputs, params):
    url = str(inputs.get("url") or "").strip()
    host = urllib.parse.urlparse(url).hostname or ""
    ctx.security.check_network(f"http://{host}" if host else url)
    try:
        replies = await exchange(
            url,
            inputs.get("message"),
            timeout=float(params.get("timeout") or 15.0),
            headers=_headers(inputs.get("headers")),
            max_messages=int(params.get("max_messages") or 1),
        )
    except WebSocketError as exc:
        raise ConnectionError(str(exc)) from exc
    return {"messages": replies, "message": replies[0] if replies else "", "count": len(replies)}


@node(
    "net.tcp_client",
    "TCP Client",
    "Networking",
    description="Connects to a TCP host, sends a payload and reads the response.",
    inputs=[inp("host", DataType.STRING), inp("port", DataType.INTEGER), inp("payload", DataType.ANY, None)],
    outputs=[out("response", DataType.STRING), out("bytes", DataType.BYTES)],
    params=[ParamSpec("timeout", "Timeout (s)", "float", 10.0), ParamSpec("encoding", "Encoding", "text", "utf-8")],
    pure=False,
    keywords=("socket", "tcp"),
)
async def tcp_client(ctx, inputs, params):
    host = str(inputs.get("host") or "").strip()
    if not host:
        raise ValueError("'host' input is empty")
    port = int(inputs.get("port") or 0)
    if not 0 < port < 65536:
        raise ValueError("'port' must be between 1 and 65535")
    ctx.security.check_network(f"tcp://{host}:{port}")
    payload = inputs.get("payload")
    raw = b"" if payload is None else (payload if isinstance(payload, bytes) else str(payload).encode(str(params.get("encoding") or "utf-8")))
    timeout = float(params.get("timeout") or 10.0)

    async def talk() -> bytes:
        reader, writer = await asyncio.open_connection(host, port, ssl=ssl.create_default_context() if False else None)
        try:
            if raw:
                writer.write(raw)
                await writer.drain()
            try:
                return await reader.read(65536)
            except asyncio.IncompleteReadError as exc:
                return exc.partial
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    try:
        response = await asyncio.wait_for(talk(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise ConnectionError(f"TCP connection to {host}:{port} timed out") from exc
    except OSError as exc:
        raise ConnectionError(f"TCP connection to {host}:{port} failed: {exc}") from exc
    return {"response": response.decode(str(params.get("encoding") or "utf-8"), "replace"), "bytes": response}


@node(
    "net.url_encode",
    "URL Encode",
    "Networking",
    inputs=[inp("value", DataType.ANY)],
    outputs=[out("text", DataType.STRING)],
    params=[ParamSpec("mode", "Mode", "choice", "query", choices=("query", "path", "full"))],
    codegen="python",
)
def url_encode(ctx, inputs, params):
    value = inputs.get("value")
    mode = str(params.get("mode") or "query")
    if isinstance(value, dict):
        return {"text": urllib.parse.urlencode(value, doseq=True)}
    text = "" if value is None else str(value)
    if mode == "path":
        return {"text": urllib.parse.quote(text, safe="/")}
    if mode == "full":
        return {"text": urllib.parse.quote(text)}
    return {"text": urllib.parse.quote_plus(text)}


@node(
    "net.basic_auth",
    "Basic Auth Header",
    "Networking",
    inputs=[inp("username", DataType.STRING), inp("password", DataType.STRING)],
    outputs=[out("header", DataType.STRING)],
    codegen="python",
)
def basic_auth(ctx, inputs, params):
    raw = f"{inputs.get('username') or ''}:{inputs.get('password') or ''}".encode("utf-8")
    return {"header": "Basic " + base64.b64encode(raw).decode("ascii")}
