"""Offline scenarios through the real loop, schemas and Ollama adapter."""
import json
from types import SimpleNamespace

import pandas as pd
from jsonschema import Draft202012Validator

from agents.dataCleaning_agent import DataCleaningAgent
from dataCleaningTools import llm_client
from dataCleaningTools.effects import target_matches


def assert_matched_history(messages):
    pending = []
    for message in messages:
        if pending:
            assert message["role"] == "tool", "Recovery interrupted a tool response batch"
            pending.remove(message["tool_name"])
        else:
            assert message["role"] != "tool", "Orphaned tool response"
        if message.get("tool_calls"):
            assert not pending
            pending = [c["function"]["name"] for c in message["tool_calls"]]
    assert not pending


def test_telco_like_workflow_finishes_within_default_budget_through_ollama_adapter(tmp_path, monkeypatch):
    flags = ["Partner", "Dependents", "PhoneService", "PaperlessBilling", "Churn"]
    source = tmp_path / "telco.csv"
    pd.DataFrame({"TotalCharges": ["10", " ", "30", "50"],
                  **{column: ["Yes", "No", "Yes", "No"] for column in flags}}).to_csv(source, index=False)
    report = {"dataset_ref": {"file_path": str(source), "file_name": source.name, "rows": 4, "columns": 6},
              "column_profiles": {
                  "TotalCharges": {"dtype": "str", "missing_count": 1, "etl_cast_to": "float",
                                   "issues": [{"issue_id": "missing_values"}, {"issue_id": "type_mismatch"}]},
                  **{column: {"dtype": "str", "etl_cast_to": "boolean", "issues": [{"issue_id": "type_mismatch"}]} for column in flags}}}
    calls = []
    monkeypatch.setattr("agents.dataCleaning_agent.sandbox_status", lambda: {"selected": "not used"})
    for key in ["BIFLOW_CLEANING_MAX_TURNS", "BIFLOW_CLEANING_MAX_SECONDS"]:
        monkeypatch.delenv(key, raising=False)
    # Keep the mock at HTTP transport, not at chat_with_tools: translation,
    # schema exposure, argument validation and state changes all execute.
    def post(url, **kwargs):
        payload = kwargs["json"]
        calls.append(payload)
        assert url.endswith("/api/chat")
        assert_matched_history(payload["messages"])
        turn = len(calls)
        if turn in [1, 3, 5]:
            name = "test_method"
            if turn == 1:
                args = {"hypothesis": "Charges need numeric conversion before imputation", "columns": ["TotalCharges"],
                        "issue_ids": ["type:TotalCharges"], "operation": "convert_data_types",
                        "parameters": {"target_type": "float", "errors": "coerce"},
                        "checks": [{"column": "TotalCharges", "kind": "numeric"}]}
            elif turn == 3:
                args = {"hypothesis": "Use median for the explicitly authorized synthetic test", "columns": ["TotalCharges"],
                        "operation": "handle_missing_values", "parameters": {"strategy": "fill_median"},
                        "checks": [{"column": "TotalCharges", "kind": "no_missing"}]}
            else:
                args = {"hypothesis": "All five observed flags use Yes/No encoding", "columns": flags,
                        "operation": "convert_data_types", "parameters": {"target_type": "boolean", "errors": "raise"},
                        "checks": [{"column": c, "kind": "boolean"} for c in flags]}
        elif turn in [2, 4, 6]:
            name = "review_candidate"
            candidate = json.loads(next(m["content"] for m in reversed(payload["messages"]) if m["role"] == "tool"))
            args = {"candidate_id": candidate["candidate_id"], "decision": "apply",
                    "assessment": "Trials meet the declared checks without losing populated values; apply with full-data checks"}
        else:
            name, args = "finish", {"summary": "Charges and all flags validated"}
        schema = next(t["function"]["parameters"] for t in payload["tools"] if t["function"]["name"] == name)
        Draft202012Validator(schema).validate(args)
        data = {"message": {"tool_calls": [{"function": {"name": name, "arguments": args}}]}, "done_reason": "stop"}
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: data)
    monkeypatch.setattr(llm_client.httpx, "post", post)
    result = DataCleaningAgent(data_root=tmp_path / "versions", use_llm=True).run(report)
    assert result.validation.all_passed, result.unresolved_issues
    assert len(calls) == 7 and result.metadata["stop_reason"] == "completed"
    assert len(result.metadata["issues"]) == 7  # No duplicate missing/type findings.
    assert len(result.change_log.successful_ops()) == 3
    frame = pd.read_csv(result.final_dataset.path)
    assert not frame.TotalCharges.isna().any()
    assert all(pd.api.types.is_bool_dtype(frame[c]) for c in flags)
    assert all("suggested_type_calls" not in request["messages"][-1]["content"] for request in calls)


def test_parseable_text_does_not_count_as_completed_conversion():
    assert not target_matches(pd.Series(["10", " ", "30"]), "numeric")
    assert not target_matches(pd.Series(["True", "False"]), "boolean")
    assert not target_matches(pd.Series([1, 0]), "boolean")
    assert target_matches(pd.Series([10.0, None, 30.0]), "numeric")
    assert target_matches(pd.Series([True, False, None]), "boolean")


def test_argument_repair_waits_until_all_tool_results_are_matched(tmp_path, monkeypatch):
    source = tmp_path / "input.csv"
    source.write_text("name\na\nb\n", encoding="utf-8")
    report = {"dataset_ref": {"file_path": str(source), "file_name": source.name, "rows": 2, "columns": 1}}
    monkeypatch.setattr("agents.dataCleaning_agent.sandbox_status", lambda: {})
    count = 0
    def post(url, **kwargs):
        nonlocal count
        count += 1
        messages = kwargs["json"]["messages"]
        assert_matched_history(messages)
        if count == 1:
            calls = [{"function": {"name": "test_method", "arguments": {}}},
                     {"function": {"name": "inspect_data", "arguments": {"view": "schema"}}}]
        else:
            assert any("Data/method error returned" in (m.get("content") or "") for m in messages if m["role"] == "user")
            calls = [{"function": {"name": "finish", "arguments": {"summary": "No data cleaning required"}}}]
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"message": {"tool_calls": calls}})
    monkeypatch.setattr(llm_client.httpx, "post", post)
    result = DataCleaningAgent(data_root=tmp_path / "versions", use_llm=True).run(report)
    assert result.validation.all_passed and count == 2
