"""Groq chat-completions client used by the data-cleaning agent.

Set GROQ_API_KEY and optionally GROQ_MODEL in the project-root .env file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

from dotenv import load_dotenv
from groq.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def llm_configured() -> bool:
    """Return whether a Groq API key is available."""
    return bool(os.environ.get("GROQ_API_KEY") or os.environ.get("BIFLOW_LLM_API_KEY"))


def get_client():
    from groq import Groq

    api_key = os.environ.get("GROQ_API_KEY") or os.environ.get("BIFLOW_LLM_API_KEY")
    if not api_key:
        raise RuntimeError("Groq is not configured; set GROQ_API_KEY in .env.")
    return Groq(api_key=api_key)


def default_model() -> str:
    return os.environ.get("GROQ_MODEL") or os.environ.get(
        "BIFLOW_LLM_MODEL", "llama-3.3-70b-versatile"
    )


def chat_with_tools(
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
        tool_choice="auto",
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
    }