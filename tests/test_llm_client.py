import threading
from types import SimpleNamespace

import pytest

from dataCleaningTools import llm_client

TOOLS = [{"type": "function", "function": {"name": "inspect_schema", "parameters": {"type": "object", "properties": {}}}}]


@pytest.fixture(autouse=True)
def local_config(monkeypatch):
    for name in ("BIFLOW_OLLAMA_TIMEOUT", "BIFLOW_OLLAMA_NUM_CTX", "BIFLOW_OLLAMA_NUM_PREDICT"):
        monkeypatch.delenv(name, raising=False)
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


def test_only_ollama_is_contacted_even_with_old_cloud_settings(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "must-not-be-sent")
    monkeypatch.setenv("GROQ_MODEL", "must-not-be-used")
    monkeypatch.setenv("BIFLOW_CLEANING_PROVIDER", "groq")
    calls = mock_local(monkeypatch)
    assert llm_client.llm_configured()
    result = llm_client.chat_with_tools([{"role": "user", "content": "Inspect synthetic data"}], TOOLS)
    assert result["provider"] == "ollama" and result["model"] == "qwen2.5:7b"
    assert result["tool_calls"][0]["name"] == "inspect_schema"
    url, kwargs = calls[0]
    assert url == "http://localhost:11434/api/chat"
    assert "headers" not in kwargs
    assert kwargs["json"]["options"]["num_ctx"] == 8192
    assert kwargs["json"]["options"]["num_predict"] == 1024
    assert kwargs["json"]["keep_alive"] == "15m"


def test_native_history_has_matched_tool_names_and_structured_arguments(monkeypatch):
    calls = mock_local(monkeypatch)
    messages = [{"role": "assistant", "content": None, "tool_calls": [{"id": "call-1", "type": "function",
                 "function": {"name": "inspect_schema", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "call-1", "content": '{"rows":2}'}]
    llm_client.chat_with_tools(messages, TOOLS)
    native = calls[0][1]["json"]["messages"]
    assert native[0]["tool_calls"][0]["function"]["arguments"] == {}
    assert native[1]["tool_name"] == "inspect_schema" and "tool_call_id" not in native[1]


def test_model_timings_and_token_rate_are_recorded(monkeypatch):
    mock_local(monkeypatch, {"message": {"content": "Done"}, "load_duration": 2_000_000_000,
                            "prompt_eval_duration": 3_000_000_000, "eval_duration": 4_000_000_000,
                            "eval_count": 80, "prompt_eval_count": 500})
    result = llm_client.chat_with_tools([], TOOLS)
    assert result["timing"]["load_seconds"] == 2
    assert result["timing"]["prompt_seconds"] == 3
    assert result["timing"]["tokens_per_second"] == 20
    assert result["usage"]["prompt_tokens"] == 500


def test_malformed_tool_name_is_rejected(monkeypatch):
    mock_local(monkeypatch, {"message": {"tool_calls": [{"function": {"name": "inspect_schema<|channel|>commentary", "arguments": {}}}]}})
    with pytest.raises(llm_client.ToolResponseError, match="unregistered"):
        llm_client.chat_with_tools([], TOOLS)


@pytest.mark.parametrize("content", [
    '{"name":"inspect_schema","arguments":{}}',
    '```json\n{"tool_calls":[{"function":{"name":"inspect_schema","arguments":{}}}]}\n```',
])
def test_complete_json_calls_are_recovered_and_labeled(monkeypatch, content):
    mock_local(monkeypatch, {"message": {"content": content}})
    result = llm_client.chat_with_tools([], TOOLS)
    assert result["tool_calls"][0]["name"] == "inspect_schema"
    assert result["tool_call_source"] == "validated_json"


@pytest.mark.parametrize("content", [
    'I plan to call {"name":"inspect_schema","arguments":{}}',
    '{"name":"not_registered","arguments":{}}',
    '{"name":"inspect_column","arguments":{}}',
    '{"name":"inspect_column","arguments":{"column":42}}',
    '[{"name":"inspect_schema","arguments":{}},{"name":"not_registered","arguments":{}}]',
])
def test_ambiguous_or_invalid_json_is_never_partially_executed(monkeypatch, content):
    from dataCleaningTools.tool_registry import TOOL_SCHEMAS
    mock_local(monkeypatch, {"message": {"content": content}})
    assert llm_client.chat_with_tools([], TOOL_SCHEMAS)["tool_calls"] == []


def test_truncated_json_response_is_not_recovered(monkeypatch):
    mock_local(monkeypatch, {"message": {"content": '{"name":"inspect_schema","arguments":{}}'}, "done_reason": "length"})
    assert not llm_client.chat_with_tools([], TOOLS)["tool_calls"]


def test_json_workflow_calls_ignore_obsolete_reference_fields(monkeypatch):
    import json
    from dataCleaningTools.workflow import WORKFLOW_SCHEMAS
    args = {"hypothesis": "Parse numeric currency values", "columns": ["Revenue"],
            "operation": "clean_numeric_string", "parameters": {},
            "checks": [{"column": "Revenue", "kind": "numeric"}],
            "issue_ids": ["profile:Revenue"], "evidence_ids": ["invalid"]}
    mock_local(monkeypatch, {"message": {"content": json.dumps({"name": "test_method", "arguments": args})}})
    result = llm_client.chat_with_tools([], WORKFLOW_SCHEMAS)
    recovered = result["tool_calls"][0]["arguments"]
    assert "issue_ids" not in recovered and "evidence_ids" not in recovered


def test_request_deadline_returns_without_waiting_for_stuck_model(monkeypatch):
    release = threading.Event()
    def delayed_post(*args, **kwargs):
        release.wait(timeout=1)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"message": {"content": "Late result"}})
    monkeypatch.setattr(llm_client.httpx, "post", delayed_post)
    events = []
    try:
        with pytest.raises(TimeoutError, match="request limit"):
            llm_client.chat_with_tools([], TOOLS, timeout=0.02, on_provider_event=events.append)
        assert events and events[0]["stage"] == "model"
    finally:
        release.set()


def test_overrides_are_explicit_and_request_uses_remaining_run_budget(monkeypatch):
    calls = mock_local(monkeypatch)
    monkeypatch.setenv("BIFLOW_OLLAMA_NUM_CTX", "4096")
    monkeypatch.setenv("BIFLOW_OLLAMA_NUM_PREDICT", "512")
    llm_client.chat_with_tools([], TOOLS, model="local-test-model", timeout=7)
    assert calls[0][1]["json"]["model"] == "local-test-model"
    assert calls[0][1]["json"]["options"]["num_ctx"] == 4096
    assert calls[0][1]["timeout"].read == 7
