import json
import threading
from types import SimpleNamespace

import pytest

from dataCleaningTools import llm_client
from tests.test_simple_workflow import flat

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
    assert kwargs["json"]["options"]["num_predict"] == 2048
    assert kwargs["json"]["keep_alive"] == "15m"


def test_structured_correction_uses_format_and_validates_json(monkeypatch):
    from dataCleaningTools.self_correction import REPAIR_TOOL
    value = {"code": "def transform(df):\n    return df", "hypothesis": "Preserve values"}
    calls = mock_local(monkeypatch, {"message": {"content": json.dumps(value)}, "done_reason": "stop"})
    result = llm_client.chat_with_tools([{"role": "user", "content": "Correct the failed method"}], [REPAIR_TOOL], structured=True)
    request = calls[0][1]["json"]
    assert "tools" not in request
    assert request["format"] == REPAIR_TOOL["function"]["parameters"]
    assert result["tool_calls"][0]["arguments"] == value
    assert result["tool_call_source"] == "structured_json"
    assert result["raw_response"]["message"]["content"] == json.dumps(value)


@pytest.mark.parametrize("content,finish", [("Here is your fixed code: ```python...```", "stop"),
    (json.dumps({"code": "incomplete fields"}), "stop"),
    (json.dumps({"code": "def transform(df): return df", "hypothesis": "Preserve"}), "length")])
def test_structured_correction_rejects_prose_invalid_schema_and_truncation(monkeypatch, content, finish):
    from dataCleaningTools.self_correction import REPAIR_TOOL
    mock_local(monkeypatch, {"message": {"content": content}, "done_reason": finish})
    result = llm_client.chat_with_tools([{"role": "user", "content": "Repair"}], [REPAIR_TOOL], structured=True)
    assert not result["tool_calls"] and result["response_issue"]
    assert result["raw_response"]["message"]["content"] == content


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
    from dataCleaningTools.workflow import SCHEMAS_LIST as TOOL_SCHEMAS
    mock_local(monkeypatch, {"message": {"content": content}})
    assert llm_client.chat_with_tools([], TOOL_SCHEMAS)["tool_calls"] == []


def test_truncated_json_response_is_not_recovered(monkeypatch):
    mock_local(monkeypatch, {"message": {"content": '{"name":"inspect_schema","arguments":{}}'}, "done_reason": "length"})
    result = llm_client.chat_with_tools([], TOOLS)
    assert not result["tool_calls"]
    assert result["response_issue"]["kind"] == "truncated"
    assert result["tool_call_source"] == "none"


def test_invalid_json_call_retains_the_argument_error_for_repair(monkeypatch):
    from dataCleaningTools.workflow import SCHEMAS_LIST
    mock_local(monkeypatch, {"message": {"content": '{"name":"test_builtin","arguments":{"columns":["Revenue"]}}'}})
    result = llm_client.chat_with_tools([], SCHEMAS_LIST)
    from dataCleaningTools.workflow import validate_request
    call = result["tool_calls"][0]
    error = validate_request(call["name"], call["arguments"])
    assert "hypothesis" in error["error"]


def test_json_workflow_calls_ignore_obsolete_reference_fields(monkeypatch):
    import json
    from dataCleaningTools.workflow import SCHEMAS_LIST
    args = {"hypothesis": "Parse numeric currency values", "columns": ["Revenue"],
            "operation": "clean_numeric_string", "parameters": {},
            "checks": [{"column": "Revenue", "kind": "numeric"}],
            "issue_ids": ["profile:Revenue"], "evidence_ids": ["invalid"]}
    mock_local(monkeypatch, {"message": {"content": json.dumps({"name": "test_builtin", "arguments": args})}})
    result = llm_client.chat_with_tools([], SCHEMAS_LIST)
    recovered = result["tool_calls"][0]["arguments"]
    from dataCleaningTools.contracts import model_arguments
    assert recovered == args  # Preserve the model request for the executor audit.
    canonical = model_arguments("test_builtin", recovered)
    assert "issue_ids" not in canonical and "evidence_ids" not in canonical


def test_json_method_normalizes_nested_columns_but_requires_real_hypothesis(monkeypatch):
    from dataCleaningTools.workflow import SCHEMAS_LIST
    args = {"hypothesis": "Observed numeric charges have missing entries; use the documented zero default for this test only",
            "operation": "handle_missing_values",
            "parameters": {"columns": ["TotalCharges"], "strategy": "fill_constant", "fill_value": 0}}
    mock_local(monkeypatch, {"message": {"content": json.dumps({"name": "test_builtin", "arguments": args})}})
    result = llm_client.chat_with_tools([], SCHEMAS_LIST)
    from dataCleaningTools.contracts import model_arguments
    from dataCleaningTools.workflow import validate_request
    raw = result["tool_calls"][0]["arguments"]
    assert raw == args
    recovered = model_arguments("test_builtin", raw)
    assert validate_request("test_builtin", recovered) is None
    assert recovered["columns"] == ["TotalCharges"]
    assert "columns" not in recovered["parameters"]
    assert recovered["hypothesis"] == args["hypothesis"]
    del args["hypothesis"]
    mock_local(monkeypatch, {"message": {"content": json.dumps({"name": "test_builtin", "arguments": args})}})
    result = llm_client.chat_with_tools([], SCHEMAS_LIST)
    raw = result["tool_calls"][0]["arguments"]
    assert "hypothesis" in validate_request("test_builtin", model_arguments("test_builtin", raw))["error"]


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


@pytest.mark.parametrize("structured", [False, True])
def test_truncated_native_calls_are_never_returned_for_execution(monkeypatch, structured):
    mock_local(monkeypatch, {"message": {"content": "", "tool_calls": [
        {"function": {"name": "inspect_schema", "arguments": {}}}]}, "done_reason": "length"})
    result = llm_client.chat_with_tools([], TOOLS, structured=structured)
    assert result["tool_calls"] == [] and result["response_issue"]["kind"] == "truncated"


@pytest.mark.parametrize("payload", [[], {"message": []}, {"message": {"content": ["bad"]}},
    {"message": {"tool_calls": {"function": {}}}}, {"message": {"tool_calls": [None]}},
    {"message": {"tool_calls": [{"function": []}]}},
    {"message": {"tool_calls": [{"function": {"name": [], "arguments": {}}}]}},
    {"message": {"tool_calls": [{"function": {"name": "inspect_schema", "arguments": []}}]}}])
def test_malformed_response_shapes_produce_controlled_errors(monkeypatch, payload):
    monkeypatch.setattr(llm_client.httpx, "post", lambda *a, **k:
        SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload))
    with pytest.raises(llm_client.ToolResponseError):
        llm_client.chat_with_tools([], TOOLS)


def test_native_index_metadata_is_accepted_and_string_arguments_are_decoded(monkeypatch):
    mock_local(monkeypatch, {"message": {"tool_calls": [{"id": "native-id", "function": {
        "index": 0, "name": "inspect_schema", "arguments": "{}"}}]}})
    result = llm_client.chat_with_tools([], TOOLS)
    assert result["tool_calls"][0]["arguments"] == {}


@pytest.mark.parametrize("native", [True, False])
def test_invalid_action_arguments_reach_same_executor_feedback(monkeypatch, flat, native):
    from dataCleaningTools.workflow import SCHEMAS_LIST
    state, executor = flat
    args = {"columns": ["amount"]}  # Explanation and method are deliberately missing.
    envelope = {"name": "test_builtin", "arguments": args}
    message = {"tool_calls": [{"function": envelope}]} if native else {"content": json.dumps(envelope)}
    mock_local(monkeypatch, {"message": message})
    call = llm_client.chat_with_tools([], SCHEMAS_LIST)["tool_calls"][0]
    result = json.loads(executor.execute(call["name"], call["arguments"]))
    assert result["error_kind"] == "invalid_tool_arguments"
    assert "hypothesis" in result["error"] and result["recovery_prompt"]["case"] == "arguments"
    assert state.events[-1]["arguments"] == args and not state.method_candidates
    assert state.current_ref.version == "V1"


@pytest.mark.parametrize("messages", [
    [{"role": "tool", "tool_call_id": "missing", "tool_name": "inspect_schema", "content": "{}"}],
    [{"role": "assistant", "tool_calls": [{"id": "1", "function": {"name": "inspect_schema", "arguments": {}}}]}],
    [{"role": "assistant", "tool_calls": [{"id": "1", "function": {"name": "inspect_schema", "arguments": {}}}]},
     {"role": "tool", "tool_call_id": "1", "content": "{}"}, {"role": "tool", "tool_call_id": "1", "content": "{}"}],
])
def test_unmatched_history_is_rejected_before_http(monkeypatch, messages):
    calls = mock_local(monkeypatch)
    with pytest.raises(llm_client.ToolResponseError):
        llm_client.chat_with_tools(messages, TOOLS)
    assert not calls


def test_generation_budget_must_leave_room_for_input(monkeypatch):
    calls = mock_local(monkeypatch)
    monkeypatch.setenv("BIFLOW_OLLAMA_NUM_CTX", "2048")
    monkeypatch.setenv("BIFLOW_OLLAMA_NUM_PREDICT", "2048")
    with pytest.raises(ValueError, match="must be smaller"):
        llm_client.chat_with_tools([], TOOLS)
    assert not calls


def test_thinking_is_disabled_by_default_and_can_be_enabled(monkeypatch):
    monkeypatch.delenv("BIFLOW_OLLAMA_THINK", raising=False)
    calls = mock_local(monkeypatch)
    result = llm_client.chat_with_tools([{"role": "user", "content": "Inspect"}], TOOLS)
    assert calls[0][1]["json"]["think"] is False and result["options"]["think"] is False
    monkeypatch.setenv("BIFLOW_OLLAMA_THINK", "true")
    llm_client.chat_with_tools([{"role": "user", "content": "Inspect"}], TOOLS)
    assert calls[1][1]["json"]["think"] is True


def test_models_without_thinking_are_retried_without_the_field(monkeypatch):
    payload = {"message": {"content": "", "tool_calls": [{"function": {"name": "inspect_schema", "arguments": {}}}]}, "done_reason": "stop"}
    sent = []
    def post(url, **kwargs):
        sent.append(dict(kwargs["json"]))
        if "think" in kwargs["json"]:
            return SimpleNamespace(status_code=400, text='{"error":"model does not support thinking"}',
                                   raise_for_status=lambda: None, json=lambda: {})
        return SimpleNamespace(status_code=200, text="", raise_for_status=lambda: None, json=lambda: payload)
    monkeypatch.setattr(llm_client.httpx, "post", post)
    result = llm_client.chat_with_tools([{"role": "user", "content": "Inspect"}], TOOLS)
    assert len(sent) == 2 and "think" not in sent[1]
    assert result["tool_calls"][0]["name"] == "inspect_schema" and result["options"]["think"] is None
