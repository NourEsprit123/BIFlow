from types import SimpleNamespace

import pytest

from dataCleaningTools import llm_client


TOOLS = [{"type": "function", "function": {"name": "inspect_schema", "parameters": {"type": "object", "properties": {}}}}]


@pytest.fixture(autouse=True)
def local_config(monkeypatch):
    monkeypatch.setenv("BIFLOW_CLEANING_PROVIDER", "auto")
    monkeypatch.setenv("BIFLOW_OLLAMA_FALLBACK", "true")
    monkeypatch.setenv("BIFLOW_CLEANING_OLLAMA_MODEL", "qwen2.5:7b")
    monkeypatch.setenv("BIFLOW_CLEANING_OLLAMA_HOST", "http://localhost:11434")


def mock_local(monkeypatch, payload=None):
    calls = []
    payload = payload or {"message": {"content": "", "tool_calls": [{"function": {"name": "inspect_schema", "arguments": {}}}]}, "done_reason": "stop"}
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)
    monkeypatch.setattr(llm_client.httpx, "post", post)
    return calls


def test_no_groq_key_uses_local_qwen_and_registered_tools(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("BIFLOW_LLM_API_KEY", raising=False)
    calls = mock_local(monkeypatch)
    assert llm_client.llm_configured()
    result = llm_client.chat_with_tools([{"role": "user", "content": "Inspect synthetic data"}], TOOLS)
    assert result["provider"] == "ollama" and result["model"] == "qwen2.5:7b"
    assert result["tool_calls"][0]["name"] == "inspect_schema"
    assert calls[0][0] == "http://localhost:11434/api/chat"
    assert calls[0][1]["json"]["tools"] == TOOLS and calls[0][1]["json"]["stream"] is False
    assert "headers" not in calls[0][1]


def test_groq_failure_falls_back_without_losing_tool_history(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-key")
    def unavailable(*a, **k):
        raise RuntimeError("Synthetic Groq outage")
    monkeypatch.setattr(llm_client, "_groq_chat", unavailable)
    calls = mock_local(monkeypatch)
    messages = [{"role": "assistant", "content": None, "tool_calls": [{"id": "groq-1", "type": "function",
                 "function": {"name": "inspect_schema", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "groq-1", "content": '{"rows":2}'}]
    result = llm_client.chat_with_tools(messages, TOOLS)
    assert "Synthetic Groq outage" in result["fallback_reason"]
    native = calls[0][1]["json"]["messages"]
    assert native[0]["tool_calls"][0]["function"]["arguments"] == {}
    assert native[1]["tool_name"] == "inspect_schema" and "tool_call_id" not in native[1]


def test_disabled_fallback_preserves_original_provider_error(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-key")
    monkeypatch.setenv("BIFLOW_OLLAMA_FALLBACK", "false")
    def unavailable(*a, **k): raise RuntimeError("Primary unavailable")
    monkeypatch.setattr(llm_client, "_groq_chat", unavailable)
    monkeypatch.setattr(llm_client, "_ollama_chat", lambda *a, **k: pytest.fail("Fallback disabled"))
    with pytest.raises(RuntimeError, match="Primary unavailable"):
        llm_client.chat_with_tools([], TOOLS)


def test_both_providers_failing_reports_both_causes(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-key")
    def unavailable(*a, **k): raise RuntimeError("Primary unavailable")
    def local_unavailable(*a, **k): raise RuntimeError("Ollama not running")
    monkeypatch.setattr(llm_client, "_groq_chat", unavailable)
    monkeypatch.setattr(llm_client, "_ollama_chat", local_unavailable)
    with pytest.raises(RuntimeError, match="Primary unavailable.*Ollama not running"):
        llm_client.chat_with_tools([], TOOLS)


def test_local_malformed_tool_name_is_rejected(monkeypatch):
    mock_local(monkeypatch, {"message": {"tool_calls": [{"function": {"name": "inspect_schema<|channel|>commentary", "arguments": {}}}]}})
    with pytest.raises(llm_client.ToolResponseError, match="unregistered"):
        llm_client.chat_with_tools([], TOOLS, provider="ollama")


def test_fallback_provider_is_pinned_and_actual_model_saved_for_remaining_turns(tmp_path, monkeypatch):
    from agents.dataCleaning_agent import DataCleaningAgent
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-key")
    primary_calls, local_calls = [], []
    def unavailable(*a, **k):
        primary_calls.append(1)
        raise RuntimeError("Synthetic rate limit")
    def local(*a, **k):
        name = "inspect_schema" if not local_calls else "finish"
        local_calls.append(name)
        return {"content": "", "provider": "ollama", "model": "qwen2.5:7b", "tool_calls": [
            {"id": name, "name": name, "arguments": {} if name == "inspect_schema" else {"summary": "Inspected synthetic data"}}]}
    monkeypatch.setattr(llm_client, "_groq_chat", unavailable)
    monkeypatch.setattr(llm_client, "_ollama_chat", local)
    monkeypatch.setattr("agents.dataCleaning_agent.sandbox_status", lambda: {"selected": "fallback"})
    source = tmp_path / "input.csv"
    source.write_text("value\n1\n2\n", encoding="utf-8")
    report = {"dataset_ref": {"file_path": str(source), "file_name": source.name, "rows": 2, "columns": 1}}
    result = DataCleaningAgent(data_root=tmp_path / "runs", use_llm=True).run(report)
    assert result.validation.all_passed
    assert len(primary_calls) == 1 and len(local_calls) == 2
    assert result.metadata["provider"] == "ollama" and result.metadata["model"] == "qwen2.5:7b"
    assert len(result.metadata["provider_switches"]) == 1
