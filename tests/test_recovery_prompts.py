import json
from pathlib import Path

import pandas as pd
import pytest

from agents.dataCleaning_agent import DataCleaningAgent, _tool_feedback
from dataCleaningTools.recovery import build_prompt
from dataCleaningTools.tool_registry import AgentSessionState, ToolExecutor
from dataCleaningTools.versioning import DatasetVersionManager


@pytest.fixture
def executor(tmp_path):
    source = tmp_path / "data.csv"
    pd.DataFrame({"amount": [1.0, None, 3.0], "text": ["10", "bad", "20"]}).to_csv(source, index=False)
    manager = DatasetVersionManager(tmp_path / "versions")
    original = manager.register_original(source, dataset_id="test")
    state = AgentSessionState(manager=manager, dataset_id="test", source_ref=original,
        current_ref=manager.create_working_copy(original), required_missing=["amount"], required_targets={"text": "float"})
    return ToolExecutor(state)


def test_imputation_error_returns_specific_prompt_and_real_column_measurements(executor):
    args = {"hypothesis": "Median fill", "columns": ["text"], "operation": "handle_missing_values",
            "parameters": {"strategy": "fill_median"}}
    result = json.loads(executor.execute("test_method", args))
    prompt = result["recovery_prompt"]
    assert prompt["case"] == "imputation"
    assert "requires numeric" in prompt["context"]["error"]
    assert prompt["context"]["working_columns"]["text"]["examples"] == ["10", "bad", "20"]
    assert prompt["context"]["parameters"]["strategy"] == "fill_median"
    trace = json.loads((Path(executor.state.current_ref.path).parent / "execution_trace.json").read_text())
    assert trace["events"][-1]["result"]["recovery_prompt"] == prompt
    assert "recovery_prompt" not in json.loads(_tool_feedback(json.dumps(result)))


@pytest.mark.parametrize("tool,args,result,expected", [
    ("test_method", {"operation": "handle_missing_values"}, {"success": False, "error_kind": "invalid_tool_arguments", "error": "missing columns"}, "arguments"),
    ("test_method", {"operation": "convert_data_types"}, {"success": False, "error": "Cannot parse 'bad'"}, "conversion"),
    ("test_method", {"operation": "convert_data_types"}, {"success": False, "effect": {"rules": [{"rule_name": "no_new_missing:text", "passed": False}]}}, "data_loss"),
    ("test_method", {"code": "def transform(df): return df"}, {"success": False, "trials": [{"partition": "sample", "success": False, "error": "pipe unavailable", "error_kind": "sandbox_unavailable"}]}, "sandbox_unavailable"),
    ("test_method", {"code": "def transform(df): return df"}, {"success": False, "trials": [{"partition": "sample", "success": False, "error": "KeyError: amount", "error_kind": "sandbox_execution", "setup": "irrelevant setup text"}]}, "sandbox_execution"),
    ("test_method", {"code": "def transform(df): return df"}, {"success": False, "trials": [{"partition": "sample", "success": False, "error": "Connection refused inside Python", "error_kind": "sandbox_execution"}]}, "sandbox_execution"),
    ("test_method", {"code": "def transform(df): return df"}, {"success": False, "message": "Candidate failed trials", "trials": [{"partition": "sample", "success": False, "effect": {"rules": [{"rule_name": "expected:no_missing:amount", "passed": False}]}}]}, "validation"),
    ("test_method", {"operation": "handle_missing_values"}, {"success": False, "effect": {"rules": [{"rule_name": "row_count", "passed": False}]}}, "validation"),
    ("test_method", {}, {"success": False, "effect": {"rules": [{"rule_name": "row_count", "passed": False}]}}, "validation"),
    ("finish", {}, {"success": False, "validation": {"rules": [{"rule_name": "missing_resolved:amount", "passed": False}]}}, "final_validation"),
    ("apply_candidate", {}, {"success": True, "no_op": True}, "no_change"),
    ("apply_candidate", {}, {"success": False, "error": "Data changed since testing; test again"}, "stale_candidate"),
    ("apply_candidate", {}, {"success": False, "approval_required": True}, "approval_required"),
    ("model_response", {}, {"success": False, "error_kind": "truncated", "error": "limit reached"}, "truncated_response"),
    ("model_response", {}, {"success": False, "error": "Invalid arguments"}, "response_format"),
    ("inspect_data", {}, {"success": False, "error": "Unexpected problem"}, "general"),
])
def test_error_cases_have_distinct_prompts(executor, tool, args, result, expected):
    prompt = build_prompt(executor, tool, args, result)
    assert prompt["case"] == expected
    assert prompt["instruction"]
    assert prompt["context"]["working_version"] == "V1"


def test_failed_application_resolves_its_imputation_method(executor):
    executor.state.method_candidates["c1"] = {"operation": "handle_missing_values", "columns": ["amount"],
        "parameters": {"strategy": "fill_median"}, "base_version": "V1", "kind": "builtin"}
    prompt = build_prompt(executor, "apply_candidate", {"candidate_id": "c1"}, {"success": False,
        "details": {"full_data_effect": {"rules": [{"rule_name": "missing_resolved:amount", "passed": False}]}}})
    assert prompt["case"] == "imputation"
    assert prompt["context"]["columns"] == ["amount"]
    assert prompt["context"]["failed_checks"][0]["rule_name"] == "missing_resolved:amount"


def test_generated_full_data_check_failure_is_not_a_python_error(executor):
    executor.state.method_candidates["c1"] = {"kind": "generated", "code": "def transform(df): return df",
        "columns": ["amount"], "base_version": "V1"}
    prompt = build_prompt(executor, "apply_candidate", {"candidate_id": "c1"}, {"success": False,
        "error": "Full-data validation failed; working version preserved", "details": {
            "full_data_effect": {"rules": [{"rule_name": "expected:no_missing:amount", "passed": False}]}}})
    assert prompt["case"] == "validation"


def test_success_does_not_add_a_recovery_prompt(executor):
    assert build_prompt(executor, "test_method", {}, {"success": True}) is None


@pytest.mark.parametrize("arguments", [
    {"hypothesis": "Fill", "columns": 42},
    {"hypothesis": "Fill", "columns": [{"bad": "column"}]},
    {"hypothesis": "Fill", "columns": ["amount"], "operation": ["invalid"]},
])
def test_malformed_arguments_cannot_break_error_feedback(executor, arguments):
    result = json.loads(executor.execute("test_method", arguments))
    assert not result["success"] and result["recovery_prompt"]["case"] == "arguments"


def test_actual_imputation_error_reaches_next_model_turn(tmp_path, monkeypatch):
    source = tmp_path / "input.csv"
    pd.DataFrame({"amount": ["10", "bad", None]}).to_csv(source, index=False)
    report = {"dataset_ref": {"file_path": str(source), "file_name": source.name, "rows": 3, "columns": 1},
              "column_profiles": {"amount": {"dtype": "str", "missing_count": 1, "etl_cast_to": "float"}}}
    monkeypatch.setattr("agents.dataCleaning_agent.sandbox_status", lambda: {})
    turns = []
    def respond(messages, tools, **kwargs):
        turns.append(messages)
        if len(turns) == 1:
            name, args = "test_method", {"hypothesis": "Fill charges", "columns": ["amount"],
                "operation": "handle_missing_values", "parameters": {"strategy": "fill_median"}}
        elif len(turns) == 2:
            feedback = [json.loads(m["content"]) for m in messages if m["role"] == "user" and m["content"].startswith('{"case":')][-1]
            assert feedback["case"] == "imputation"
            assert "requires numeric" in feedback["context"]["error"]
            name, args = "flag_for_review", {"columns": ["amount"], "reason": "Unknown meaning of bad charge"}
        else:
            name, args = "finish", {"summary": "Business decision required"}
        return {"tool_calls": [{"id": str(len(turns)), "name": name, "arguments": args}]}
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", respond)
    result = DataCleaningAgent(data_root=tmp_path / "versions", use_llm=True).run(report)
    assert len(turns) == 3 and result.validation.exceptions
    assert not result.validation.all_passed
