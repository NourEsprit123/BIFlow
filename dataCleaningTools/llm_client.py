"""Local-only Ollama tool calling for the cleaning agent (no cloud provider)."""
from __future__ import annotations

import json
import math
import os
import queue
import threading
import time
from pathlib import Path
from uuid import uuid4

import httpx
from jsonschema import Draft202012Validator
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def llm_configured() -> bool:
    # Local availability is checked by the request, not by an external API key.
    return True


def default_model() -> str:
    return os.environ.get("BIFLOW_CLEANING_OLLAMA_MODEL") or os.environ.get("OLLAMA_MODEL") or "qwen2.5:7b"


def positive_setting(name, default, integer=False):
    value = int(os.environ.get(name, str(default))) if integer else float(os.environ.get(name, str(default)))
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return value


def _post_with_progress(url, payload, timeout, callback, *, headers=None, label="Ollama"):
    """Keep Streamlit updates on its main thread while bounded HTTP I/O waits."""
    results = queue.Queue(maxsize=1)
    def send():
        try:
            options = {"json": payload, "timeout": httpx.Timeout(timeout, connect=min(5.0, timeout))}
            if headers is not None:
                options["headers"] = headers
            response = httpx.post(url, **options)
            results.put((response, None))
        except Exception as exc:
            results.put((None, exc))
    started = time.monotonic()
    threading.Thread(target=send, daemon=True, name="biflow-ollama-request").start()
    next_update = 0.0
    while True:
        elapsed = time.monotonic() - started
        if elapsed >= timeout:
            raise TimeoutError(f"{label} exceeded the {timeout:.0f}s request limit; no further actions will be applied from this request")
        if callback and elapsed >= next_update:
            callback({"phase": f"waiting for {label} · {elapsed:.0f}s", "stage": "model", "request_elapsed_seconds": elapsed})
            next_update = elapsed + 1.0
        try:
            response, error = results.get(timeout=min(0.25, timeout - elapsed))
        except queue.Empty:
            continue
        if error:
            raise error
        return response

class ToolResponseError(ValueError):
    status_code = 400
    body = {"code": "tool_use_failed"}


def _ollama_messages(messages):
    translated = []
    call_names = {}
    for message in messages:
        if call_names and message["role"] != "tool":
            raise ToolResponseError("Assistant tool calls are missing matching responses")
        item = {"role": message["role"], "content": message.get("content") or ""}
        if message.get("tool_calls"):
            item["tool_calls"] = []
            for call in message["tool_calls"]:
                function = call["function"]
                arguments = function.get("arguments") or {}
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                item["tool_calls"].append({"function": {"name": function["name"], "arguments": arguments}})
                if call["id"] in call_names:
                    raise ToolResponseError("Assistant tool call IDs must be unique")
                call_names[call["id"]] = function["name"]
        if message["role"] == "tool":
            name = call_names.pop(message.get("tool_call_id"), None)
            if not name:
                raise ToolResponseError("Tool response has no matching assistant function call")
            item["tool_name"] = name
        translated.append(item)
    if call_names:
        raise ToolResponseError("Assistant tool calls are missing matching responses")
    return translated


def _decode_calls(entries, tools):
    """Parse envelopes only; the executor owns action argument validation.

    Validate the entire batch before returning any call. Preserve raw arguments
    so native and JSON fallback requests reach correction and audit identically.
    """
    allowed = {t["function"]["name"] for t in tools}
    if not isinstance(entries, list) or not 1 <= len(entries) <= 8:
        raise ToolResponseError("Return between one and eight tool calls")
    calls = []
    for entry in entries:
        if isinstance(entry, dict) and set(entry) == {"function"}:
            entry = entry["function"]
        if not isinstance(entry, dict) or set(entry) != {"name", "arguments"}:
            raise ToolResponseError("A call must contain exactly name and arguments")
        name, arguments = entry["name"], entry["arguments"]
        if not isinstance(name, str) or name not in allowed:
            raise ToolResponseError(f"Ollama generated an unregistered tool name: {name}")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except ValueError as exc:
                raise ToolResponseError("Ollama tool arguments must be valid JSON") from exc
        if not isinstance(arguments, dict):
            raise ToolResponseError("Ollama tool arguments must be an object")
        calls.append({"id": "ollama-" + uuid4().hex[:12], "name": name, "arguments": arguments})
    return calls


def _json_tool_calls(content, tools, diagnostics):
    """Accept a complete JSON envelope, never extract calls from prose."""
    text = content.strip()
    if text.startswith("```json\n") and text.endswith("\n```"):
        text = text[8:-4].strip()
    try:
        value = json.loads(text)
        if isinstance(value, dict) and set(value) == {"tool_calls"}:
            value = value["tool_calls"]
        return _decode_calls(value if isinstance(value, list) else [value], tools)
    except (ValueError, TypeError) as exc:
        diagnostics.append(str(exc) if isinstance(exc, ToolResponseError) else "Return a complete JSON call without surrounding prose")
        return []


def chat_with_tools(messages, tools, *, model=None, temperature=0.1, on_provider_event=None, timeout=None, structured=False):
    """One local inference request; cloud environment variables are ignored."""
    host = (os.environ.get("BIFLOW_CLEANING_OLLAMA_HOST") or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
    model = model or default_model()
    configured_timeout = positive_setting("BIFLOW_OLLAMA_TIMEOUT", 90)
    timeout = min(configured_timeout, timeout) if timeout is not None else configured_timeout
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Ollama request budget has expired")
    options = {"temperature": temperature,
               "num_ctx": positive_setting("BIFLOW_OLLAMA_NUM_CTX", 8192, integer=True),
               "num_predict": positive_setting("BIFLOW_OLLAMA_NUM_PREDICT", 2048, integer=True)}
    if options["num_predict"] >= options["num_ctx"]:
        raise ValueError("BIFLOW_OLLAMA_NUM_PREDICT must be smaller than BIFLOW_OLLAMA_NUM_CTX")
    started = time.monotonic()
    # Thinking models (qwen3) otherwise emit thousands of hidden reasoning tokens per call; the agent never reads them.
    think = os.environ.get("BIFLOW_OLLAMA_THINK", "false").strip().lower() == "true"
    payload = {"model": model, "messages": _ollama_messages(messages), "tools": tools,
               "stream": False, "keep_alive": "15m", "options": options, "think": think}
    if structured:
        if len(tools) != 1:
            raise ValueError("Structured correction requires exactly one response schema")
        schema = tools[0]["function"]["parameters"]
        payload.pop("tools")
        payload["format"] = schema
        payload["messages"].append({"role": "user", "content": "Return only a JSON object matching this response schema: " + json.dumps(schema)})
    try:
        response = _post_with_progress(host + "/api/chat", payload, timeout, on_provider_event)
        if getattr(response, "status_code", 200) == 400 and "thinking" in str(getattr(response, "text", "")).lower():
            # Models without a thinking mode may reject the field; retry once without it.
            payload.pop("think")
            response = _post_with_progress(host + "/api/chat", payload, max(timeout - (time.monotonic() - started), 0.001), on_provider_event)
        response.raise_for_status()
        data = response.json()
    except TimeoutError:
        raise
    except httpx.TimeoutException as exc:
        raise TimeoutError(f"Local Ollama request timed out at {host}: {exc}") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError(f"Ollama request failed at {host}. Check `ollama run {model}`. Details: {exc}") from exc
    if not isinstance(data, dict):
        raise ToolResponseError("Ollama response must be a JSON object")
    if data.get("error"):
        raise RuntimeError(f"Ollama error: {data['error']}")
    message = data.get("message")
    if not isinstance(message, dict):
        raise ToolResponseError("Ollama returned no structured message")
    content = message.get("content") or ""
    if not isinstance(content, str):
        raise ToolResponseError("Ollama message content must be text")
    calls, diagnostics = [], []
    call_source = "none"
    if data.get("done_reason") == "length":
        diagnostics.append("Response reached the generation limit; return a shorter complete action")
    elif structured:
        call_source = "structured_json"
        try:
            value = json.loads(content)
            errors = list(Draft202012Validator(schema).iter_errors(value))
            if errors:
                diagnostics.extend(e.message for e in errors)
            else:
                calls = _decode_calls([{"name": tools[0]["function"]["name"], "arguments": value}], tools)
        except (TypeError, ValueError) as exc:
            diagnostics.append(f"Invalid structured correction JSON: {exc}")
    elif message.get("tool_calls"):
        # Ollama may attach an index/id to native envelopes; only the function
        # object is relevant. Argument fields remain untouched for dispatch.
        raw = message["tool_calls"]
        if not isinstance(raw, list) or any(not isinstance(c, dict) or not isinstance(c.get("function"), dict) for c in raw):
            raise ToolResponseError("Ollama tool_calls must be a list of call objects")
        calls = _decode_calls([{k: c["function"][k] for k in ("name", "arguments") if k in c["function"]} for c in raw], tools)
        call_source = "native"
    else:
        calls = _json_tool_calls(content, tools, diagnostics)
        call_source = "validated_json" if calls else "none"
    def seconds(key):
        value = data.get(key)
        return value / 1e9 if isinstance(value, (int, float)) else None
    generated_seconds = seconds("eval_duration")
    tokens = data.get("eval_count")
    return {**({"raw_response": data} if structured else {}),
            "content": content, "tool_calls": calls, "raw_role": "assistant",
            "provider": "ollama", "model": model, "finish_reason": data.get("done_reason"),
            "tool_call_source": call_source,
            "response_issue": {"kind": "truncated" if data.get("done_reason") == "length" else "invalid_response", "message": diagnostics[0]} if diagnostics else None,
            "usage": {"prompt_tokens": data.get("prompt_eval_count"), "completion_tokens": tokens},
            "timing": {"request_seconds": time.monotonic() - started, "load_seconds": seconds("load_duration"),
                       "prompt_seconds": seconds("prompt_eval_duration"), "generation_seconds": generated_seconds,
                       "tokens_per_second": tokens / generated_seconds if isinstance(tokens, (int, float)) and generated_seconds else None},
            "options": {**options, "think": payload.get("think")}}
