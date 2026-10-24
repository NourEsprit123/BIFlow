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


def _post_with_progress(url, payload, timeout, callback):
    """Keep Streamlit updates on its main thread while bounded HTTP I/O waits."""
    results = queue.Queue(maxsize=1)
    def send():
        try:
            response = httpx.post(url, json=payload, timeout=httpx.Timeout(timeout, connect=min(5.0, timeout)))
            results.put((response, None))
        except Exception as exc:
            results.put((None, exc))
    started = time.monotonic()
    threading.Thread(target=send, daemon=True, name="biflow-ollama-request").start()
    next_update = 0.0
    while True:
        elapsed = time.monotonic() - started
        if elapsed >= timeout:
            raise TimeoutError(f"Ollama exceeded the {timeout:.0f}s request limit; no further actions will be applied from this request")
        if callback and elapsed >= next_update:
            callback({"phase": f"waiting for Ollama · {elapsed:.0f}s", "stage": "model", "request_elapsed_seconds": elapsed})
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
        item = {"role": message["role"], "content": message.get("content") or ""}
        if message.get("tool_calls"):
            item["tool_calls"] = []
            for call in message["tool_calls"]:
                function = call["function"]
                arguments = function.get("arguments") or {}
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                item["tool_calls"].append({"function": {"name": function["name"], "arguments": arguments}})
                call_names[call["id"]] = function["name"]
        if message["role"] == "tool":
            name = call_names.get(message.get("tool_call_id")) or message.get("tool_name")
            if not name:
                raise ToolResponseError("Tool response has no matching assistant function call")
            item["tool_name"] = name
        translated.append(item)
    return translated


def chat_with_tools(messages, tools, *, model=None, temperature=0.1, on_provider_event=None, timeout=None):
    """One local inference request; cloud environment variables are ignored."""
    host = (os.environ.get("BIFLOW_CLEANING_OLLAMA_HOST") or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
    model = model or default_model()
    configured_timeout = positive_setting("BIFLOW_OLLAMA_TIMEOUT", 90)
    timeout = min(configured_timeout, timeout) if timeout is not None else configured_timeout
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Ollama request budget has expired")
    options = {"temperature": temperature,
               "num_ctx": positive_setting("BIFLOW_OLLAMA_NUM_CTX", 8192, integer=True),
               "num_predict": positive_setting("BIFLOW_OLLAMA_NUM_PREDICT", 1024, integer=True)}
    started = time.monotonic()
    payload = {"model": model, "messages": _ollama_messages(messages), "tools": tools,
               "stream": False, "keep_alive": "15m", "options": options}
    try:
        response = _post_with_progress(host + "/api/chat", payload, timeout, on_provider_event)
        response.raise_for_status()
        data = response.json()
    except TimeoutError:
        raise
    except httpx.TimeoutException as exc:
        raise TimeoutError(f"Local Ollama request timed out at {host}: {exc}") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError(f"Ollama request failed at {host}. Check `ollama run {model}`. Details: {exc}") from exc
    if data.get("error"):
        raise RuntimeError(f"Ollama error: {data['error']}")
    message = data.get("message")
    if not isinstance(message, dict):
        raise ToolResponseError("Ollama returned no structured message")
    allowed = {tool["function"]["name"] for tool in tools}
    calls = []
    for call in message.get("tool_calls") or []:
        function = call.get("function", {})
        name = function.get("name")
        if name not in allowed:
            raise ToolResponseError(f"Ollama generated an unregistered tool name: {name}")
        arguments = function.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except ValueError as exc:
                raise ToolResponseError("Ollama tool arguments must be valid JSON") from exc
        if not isinstance(arguments, dict):
            raise ToolResponseError("Ollama tool arguments must be an object")
        calls.append({"id": "ollama-" + uuid4().hex[:12], "name": name, "arguments": arguments})
    def seconds(key):
        value = data.get(key)
        return value / 1e9 if isinstance(value, (int, float)) else None
    generated_seconds = seconds("eval_duration")
    tokens = data.get("eval_count")
    return {"content": message.get("content") or "", "tool_calls": calls, "raw_role": "assistant",
            "provider": "ollama", "model": model, "finish_reason": data.get("done_reason"),
            "usage": {"prompt_tokens": data.get("prompt_eval_count"), "completion_tokens": tokens},
            "timing": {"request_seconds": time.monotonic() - started, "load_seconds": seconds("load_duration"),
                       "prompt_seconds": seconds("prompt_eval_duration"), "generation_seconds": generated_seconds,
                       "tokens_per_second": tokens / generated_seconds if tokens is not None and generated_seconds else None},
            "options": options}
