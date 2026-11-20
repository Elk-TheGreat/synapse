"""AI nodes.

The LLM nodes speak the OpenAI-compatible chat/embeddings protocol, which most
hosted providers and local servers (Ollama, LM Studio, vLLM) expose.  The API
key is read from an environment variable, never stored in the project file.
"""

from __future__ import annotations

import json
import os
from typing import Any

from ...typesystem import DataType
from ..base import ParamSpec, inp, node, out
from .network import _headers, _request

PROVIDERS = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://localhost:11434/v1",
    "lmstudio": "http://localhost:1234/v1",
    "custom": "",
}


def _api_key(params: dict) -> str:
    env_name = str(params.get("api_key_env") or "OPENAI_API_KEY")
    key = os.environ.get(env_name, "")
    if not key:
        raise ValueError(
            f"no API key found: set the {env_name} environment variable "
            "(or point 'API key variable' at another variable)"
        )
    return key


def _base_url(params: dict) -> str:
    explicit = str(params.get("base_url") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    provider = str(params.get("provider") or "openai")
    url = PROVIDERS.get(provider, "")
    if not url:
        raise ValueError("set 'Base URL' when using the custom provider")
    return url


def _post_json(ctx, url: str, payload: dict, params: dict, key: str) -> dict:
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    status, _, raw = _request(
        "POST",
        url,
        data=body,
        headers=headers,
        timeout=float(params.get("timeout") or 120.0),
        max_bytes=16_000_000,
    )
    if status >= 400:
        raise ConnectionError(f"{url} returned HTTP {status}: {raw[:400].decode('utf-8', 'replace')}")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"provider returned invalid JSON: {exc}") from exc


@node(
    "ai.llm_request",
    "LLM Request",
    "AI",
    description="Sends a chat completion request to an OpenAI-compatible endpoint.",
    inputs=[inp("prompt", DataType.STRING), inp("system", DataType.STRING, None), inp("messages", DataType.ARRAY, None)],
    outputs=[out("text", DataType.STRING), out("json", DataType.ANY), out("usage", DataType.DICTIONARY)],
    params=[
        ParamSpec("provider", "Provider", "choice", "openai", choices=tuple(PROVIDERS)),
        ParamSpec("base_url", "Base URL", "text", ""),
        ParamSpec("model", "Model", "text", "gpt-4o-mini"),
        ParamSpec("temperature", "Temperature", "float", 0.2),
        ParamSpec("max_tokens", "Max tokens", "int", 1024, minimum=1),
        ParamSpec("json_mode", "Request JSON output", "bool", False),
        ParamSpec("api_key_env", "API key variable", "text", "OPENAI_API_KEY"),
        ParamSpec("timeout", "Timeout (s)", "float", 120.0),
    ],
    pure=False,
    blocking=True,
    keywords=("gpt", "chat", "completion", "llm", "openai"),
)
async def llm_request(ctx, inputs, params):
    base = _base_url(params)
    ctx.security.check_network(base)
    key = _api_key(params)
    messages = inputs.get("messages")
    if not isinstance(messages, list) or not messages:
        messages = []
        system = inputs.get("system")
        if system:
            messages.append({"role": "system", "content": str(system)})
        prompt = inputs.get("prompt")
        if prompt is None:
            raise ValueError("LLM Request needs a prompt or a messages array")
        messages.append({"role": "user", "content": str(prompt)})
    payload: dict[str, Any] = {
        "model": str(params.get("model") or "gpt-4o-mini"),
        "messages": messages,
        "temperature": float(params.get("temperature") or 0.2),
        "max_tokens": int(params.get("max_tokens") or 1024),
    }
    if params.get("json_mode"):
        payload["response_format"] = {"type": "json_object"}
    response = await ctx.run_blocking(_post_json, ctx, f"{base}/chat/completions", payload, params, key)
    choices = response.get("choices") or []
    if not choices:
        raise ValueError(f"provider returned no choices: {json.dumps(response)[:300]}")
    text = (choices[0].get("message") or {}).get("content") or ""
    parsed = None
    if params.get("json_mode"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"model did not return valid JSON despite json_mode: {exc}") from exc
    return {"text": text, "json": parsed, "usage": response.get("usage") or {}}


@node(
    "ai.embeddings",
    "Embeddings",
    "AI",
    description="Requests an embedding vector from an OpenAI-compatible endpoint.",
    inputs=[inp("text", DataType.ANY)],
    outputs=[out("vector", DataType.ARRAY), out("dimension", DataType.INTEGER)],
    params=[
        ParamSpec("provider", "Provider", "choice", "openai", choices=tuple(PROVIDERS)),
        ParamSpec("base_url", "Base URL", "text", ""),
        ParamSpec("model", "Model", "text", "text-embedding-3-small"),
        ParamSpec("api_key_env", "API key variable", "text", "OPENAI_API_KEY"),
        ParamSpec("timeout", "Timeout (s)", "float", 60.0),
    ],
    pure=False,
    blocking=True,
)
async def embeddings(ctx, inputs, params):
    text = inputs.get("text")
    items = [str(t) for t in text] if isinstance(text, (list, tuple)) else [str(text or "")]
    base = _base_url(params)
    ctx.security.check_network(base)
    key = _api_key(params)
    payload = {"model": str(params.get("model") or "text-embedding-3-small"), "input": items}
    response = await ctx.run_blocking(_post_json, ctx, f"{base}/embeddings", payload, params, key)
    data = response.get("data") or []
    if not data:
        raise ValueError("provider returned no embeddings")
    vector = data[0].get("embedding") or []
    return {"vector": vector, "dimension": len(vector)}


@node(
    "ai.prompt_builder",
    "Prompt Builder",
    "AI",
    description="Fills a template with variables and produces a chat message list.",
    inputs=[inp("variables", DataType.DICTIONARY, None), inp("examples", DataType.ARRAY, None)],
    outputs=[out("prompt", DataType.STRING), out("messages", DataType.ARRAY), out("system", DataType.STRING)],
    params=[
        ParamSpec("template", "Template", "multiline", "Answer the question: {question}"),
        ParamSpec("system_prompt", "System prompt", "multiline", "You are a precise assistant."),
    ],
    codegen="python",
)
def prompt_builder(ctx, inputs, params):
    values = inputs.get("variables") or {}
    if not isinstance(values, dict):
        raise ValueError("'variables' must be a dictionary")
    template = str(params.get("template") or "")
    try:
        prompt = template.format_map({k: v for k, v in values.items()}) if values else template
    except (KeyError, ValueError) as exc:
        raise ValueError(f"cannot fill template: {exc}") from exc
    messages: list[dict] = []
    system = str(params.get("system_prompt") or "").strip()
    if system:
        messages.append({"role": "system", "content": system})
    examples = inputs.get("examples")
    if isinstance(examples, list):
        for example in examples:
            if isinstance(example, dict) and "input" in example and "output" in example:
                messages.append({"role": "user", "content": str(example["input"])})
                messages.append({"role": "assistant", "content": str(example["output"])})
    messages.append({"role": "user", "content": prompt})
    return {"prompt": prompt, "messages": messages, "system": system}


@node(
    "ai.text_classify",
    "Text Classification",
    "AI",
    description="Keyword/score-based classifier that runs locally (no API call).",
    inputs=[inp("text", DataType.STRING)],
    outputs=[out("label", DataType.STRING), out("score", DataType.FLOAT), out("scores", DataType.DICTIONARY)],
    params=[
        ParamSpec(
            "labels",
            "Labels (JSON: label -> keywords)",
            "json",
            '{"positive": ["good", "great", "love"], "negative": ["bad", "hate", "broken"], "neutral": []}',
        ),
        ParamSpec("fallback", "Fallback label", "text", "neutral"),
    ],
    codegen="python",
)
def text_classify(ctx, inputs, params):
    text = str(inputs.get("text") or "").lower()
    raw = params.get("labels")
    try:
        labels = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except json.JSONDecodeError as exc:
        raise ValueError(f"'labels' is not valid JSON: {exc}") from exc
    if not isinstance(labels, dict) or not labels:
        raise ValueError("'labels' must map label names to keyword lists")
    scores: dict[str, float] = {}
    for label, keywords in labels.items():
        words = [str(k).lower() for k in (keywords or [])]
        hits = sum(text.count(w) for w in words if w)
        scores[str(label)] = float(hits)
    best = max(scores, key=lambda k: scores[k])
    if scores[best] <= 0:
        fallback = str(params.get("fallback") or "")
        return {"label": fallback if fallback in scores else best, "score": 0.0, "scores": scores}
    return {"label": best, "score": scores[best], "scores": scores}


@node(
    "ai.structured_output",
    "Structured Output",
    "AI",
    description="Parses text as JSON and validates it against a small schema.",
    inputs=[inp("value", DataType.ANY)],
    outputs=[out("value", DataType.DICTIONARY), out("valid", DataType.BOOLEAN), out("errors", DataType.ARRAY)],
    params=[
        ParamSpec(
            "schema",
            "Schema (JSON)",
            "json",
            '{"type": "object", "required": [], "properties": {}}',
        )
    ],
    codegen="python",
)
def structured_output(ctx, inputs, params):
    raw = inputs.get("value")
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            return {"value": {}, "valid": False, "errors": [f"invalid JSON: {exc}"]}
    else:
        value = raw
    schema = params.get("schema")
    try:
        schema = json.loads(schema) if isinstance(schema, str) else (schema or {})
    except json.JSONDecodeError as exc:
        raise ValueError(f"'schema' is not valid JSON: {exc}") from exc
    errors = _validate(value, schema, path="value")
    return {"value": value if isinstance(value, dict) else {}, "valid": not errors, "errors": errors}


def _validate(value: Any, schema: dict, path: str) -> list[str]:
    errors: list[str] = []
    expected = schema.get("type")
    type_map = {
        "object": dict,
        "array": list,
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
    }
    if expected and expected in type_map:
        if not isinstance(value, type_map[expected]) or (
            expected in ("number", "integer") and isinstance(value, bool)
        ):
            return [f"{path}: expected {expected}, got {type(value).__name__}"]
    if expected == "object" and isinstance(value, dict):
        for name in schema.get("required") or []:
            if name not in value:
                errors.append(f"{path}.{name}: missing required field")
        for name, sub in (schema.get("properties") or {}).items():
            if name in value and isinstance(sub, dict):
                errors.extend(_validate(value[name], sub, f"{path}.{name}"))
    if expected == "array" and isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(_validate(item, item_schema, f"{path}[{index}]"))
    return errors


@node(
    "ai.model_select",
    "Model Selection",
    "AI",
    description="Chooses a model name for a task and reports the configured provider.",
    inputs=[],
    outputs=[out("model", DataType.STRING), out("base_url", DataType.STRING), out("provider", DataType.STRING)],
    params=[
        ParamSpec("provider", "Provider", "choice", "openai", choices=tuple(PROVIDERS)),
        ParamSpec(
            "task",
            "Task",
            "choice",
            "general",
            choices=("general", "fast", "reasoning", "vision", "embedding"),
        ),
        ParamSpec("override_model", "Override model", "text", ""),
    ],
    codegen="python",
)
def model_select(ctx, inputs, params):
    provider = str(params.get("provider") or "openai")
    task = str(params.get("task") or "general")
    catalogs = {
        "openai": {
            "general": "gpt-4o-mini",
            "fast": "gpt-4o-mini",
            "reasoning": "gpt-4o",
            "vision": "gpt-4o",
            "embedding": "text-embedding-3-small",
        },
        "openrouter": {
            "general": "openai/gpt-4o-mini",
            "fast": "openai/gpt-4o-mini",
            "reasoning": "anthropic/claude-3.5-sonnet",
            "vision": "openai/gpt-4o",
            "embedding": "openai/text-embedding-3-small",
        },
        "ollama": {
            "general": "llama3.1",
            "fast": "llama3.2:3b",
            "reasoning": "qwen2.5:14b",
            "vision": "llava",
            "embedding": "nomic-embed-text",
        },
        "lmstudio": {
            "general": "local-model",
            "fast": "local-model",
            "reasoning": "local-model",
            "vision": "local-model",
            "embedding": "local-model",
        },
    }
    model = str(params.get("override_model") or "").strip()
    if not model:
        model = catalogs.get(provider, {}).get(task, "gpt-4o-mini")
    return {
        "model": model,
        "base_url": _base_url(params),
        "provider": provider,
    }
