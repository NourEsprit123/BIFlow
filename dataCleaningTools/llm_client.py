"""Groq tool-calling client with a local Ollama fallback for the cleaning agent.

Set GROQ_API_KEY and optionally GROQ_MODEL in the project-root .env file.
"""

from __future__ import annotations

import json
import os
import math
from uuid import uuid4

import httpx
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

from dotenv import load_dotenv
from groq.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def llm_configured() -> bool:
    """An enabled local Ollama route also counts as a configured LLM."""
    provider = os.environ.get("BIFLOW_CLEANING_PROVIDER", "auto").lower()
    if provider == "ollama":
        return True
    return bool(os.environ.get("GROQ_API_KEY") or os.environ.get("BIFLOW_LLM_API_KEY")) or ollama_fallback_enabled()


def get_client():
    from groq import Groq

    api_key = os.environ.get("GROQ_API_KEY") or os.environ.get("BIFLOW_LLM_API_KEY")
    if not api_key:
        raise RuntimeError("Groq is not configured; set GROQ_API_KEY in .env.")
    return Groq(api_key=api_key, max_retries=0, timeout=60.0)


def default_model() -> str:
    return os.environ.get("GROQ_MODEL") or os.environ.get(
        "BIFLOW_LLM_MODEL", "openai/gpt-oss-20b"
    )


def _groq_chat(
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    temperature: float = 0.1,
) -> Dict[str, Any]:
    """
    One turn of chat with optional tool calls.

    Returns a normalized dict:
      {
        "content": str | None,
        "tool_calls": [ {"id", "name", "arguments": dict}, ... ],
        "raw": message object-ish
      }
    """
    client = get_client()
    model = model or default_model()

    resp = client.chat.completions.create(
        model=model,
        messages=cast(List[ChatCompletionMessageParam], messages),
        tools=cast(List[ChatCompletionToolParam], tools),
        tool_choice="required",
        parallel_tool_calls=False,
        max_completion_tokens=2048,
        temperature=temperature,
    )
    msg = resp.choices[0].message
    tool_calls = []
    if msg.tool_calls is not None:
        for tc in msg.tool_calls:
            args_raw = tc.function.arguments or "{}"
            try:
                args = json.loads(args_raw)
            except json.JSONDecodeError:
                args = {"_raw": args_raw}
            tool_calls.append(
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": args,
                }
            )

    return {
        "content": msg.content,
        "tool_calls": tool_calls,
        "raw_role": "assistant",
        "finish_reason": getattr(resp.choices[0], "finish_reason", None),
        "usage": resp.usage.model_dump() if getattr(resp, "usage", None) else None,
    }

def ollama_fallback_enabled() -> bool:
    return os.environ.get("BIFLOW_OLLAMA_FALLBACK", "true").lower() not in {"0", "false", "no", "off"}


def ollama_model() -> str:
    return os.environ.get("BIFLOW_CLEANING_OLLAMA_MODEL") or os.environ.get("OLLAMA_MODEL") or "qwen2.5:7b"


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


def _ollama_chat(messages, tools, *, temperature=0.1):
    host = (os.environ.get("BIFLOW_CLEANING_OLLAMA_HOST") or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
    model = ollama_model()
    timeout = float(os.environ.get("BIFLOW_OLLAMA_TIMEOUT", "180"))
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("BIFLOW_OLLAMA_TIMEOUT must be a positive finite number")
    try:
        response = httpx.post(
            host + "/api/chat",
            json={"model": model, "messages": _ollama_messages(messages), "tools": tools,
                  "stream": False, "options": {"temperature": temperature, "num_ctx": 16384, "num_predict": 2048}},
            timeout=httpx.Timeout(timeout, connect=5.0),
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError(f"Ollama request failed at {host}. Start Ollama and run `ollama run {model}`. Details: {exc}") from exc
    if payload.get("error"):
        raise RuntimeError(f"Ollama error: {payload['error']}")
    message = payload.get("message")
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
    return {"content": message.get("content") or "", "tool_calls": calls, "raw_role": "assistant",
            "provider": "ollama", "model": model, "finish_reason": payload.get("done_reason"),
            "usage": {"prompt_tokens": payload.get("prompt_eval_count"), "completion_tokens": payload.get("eval_count")}}


def chat_with_tools(messages, tools, *, model=None, temperature=0.1, provider=None, on_provider_event=None):
    """Groq first; optionally fail over to local Ollama using the same tool loop."""
    selected = (provider or os.environ.get("BIFLOW_CLEANING_PROVIDER", "auto")).lower()
    if selected not in {"auto", "groq", "ollama"}:
        raise ValueError("BIFLOW_CLEANING_PROVIDER must be auto, groq or ollama")
    if selected == "ollama":
        return _ollama_chat(messages, tools, temperature=temperature)
    has_key = bool(os.environ.get("GROQ_API_KEY") or os.environ.get("BIFLOW_LLM_API_KEY"))
    primary_error = None
    if has_key or selected == "groq":
        try:
            result = _groq_chat(messages, tools, model=model, temperature=temperature)
            return {**result, "provider": "groq", "model": model or default_model()}
        except Exception as exc:
            if not ollama_fallback_enabled():
                raise
            primary_error = exc
    elif not ollama_fallback_enabled():
        raise RuntimeError("No Groq key configured and Ollama fallback is disabled")
    reason = f"{type(primary_error).__name__}: {primary_error}" if primary_error else "No Groq API key configured"
    if on_provider_event:
        on_provider_event({"phase": f"switching to local Ollama ({ollama_model()})"})
    try:
        result = _ollama_chat(messages, tools, temperature=temperature)
    except ToolResponseError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Groq unavailable ({reason}); local Ollama also failed: {exc}") from exc
    return {**result, "fallback_reason": reason}
