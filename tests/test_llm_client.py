from types import SimpleNamespace

import pytest

from dataCleaningTools import llm_client
from dataCleaningTools.llm_client import default_model, get_client, llm_configured


def test_groq_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("BIFLOW_LLM_API_KEY", raising=False)
    monkeypatch.setenv("BIFLOW_OLLAMA_FALLBACK", "false")
    monkeypatch.setenv("BIFLOW_CLEANING_PROVIDER", "auto")

    assert not llm_configured()
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        get_client()


def test_groq_client_uses_groq_environment(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_MODEL", "test-model")

    client = get_client()

    assert client.api_key == "test-key"
    assert llm_configured()
    assert default_model() == "test-model"


def test_chat_with_tools_normalizes_groq_tool_calls(monkeypatch):
    class FakeCompletions:
        def create(self, **kwargs):
            self.kwargs = kwargs
            tool_call = SimpleNamespace(
                id="call-1",
                function=SimpleNamespace(name="inspect_schema", arguments="{}"),
            )
            message = SimpleNamespace(content=None, tool_calls=[tool_call])
            return SimpleNamespace(
                choices=[SimpleNamespace(message=message)]
            )

    completions = FakeCompletions()
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    monkeypatch.setattr(llm_client, "get_client", lambda: fake_client)

    response = llm_client.chat_with_tools(
        [{"role": "user", "content": "Inspect"}],
        [{"type": "function", "function": {"name": "inspect_schema"}}],
        model="test-model",
    )

    assert response["tool_calls"] == [
        {"id": "call-1", "name": "inspect_schema", "arguments": {}}
    ]
    assert completions.kwargs["model"] == "test-model"
    assert completions.kwargs["tool_choice"] == "required"
    assert completions.kwargs["parallel_tool_calls"] is False
    assert completions.kwargs["max_completion_tokens"] == 2048
