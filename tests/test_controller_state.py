from copy import deepcopy
import json
from pathlib import Path

import pandas as pd
import pytest

from agents.dataCleaning_agent import DataCleaningAgent
from tests.test_cleaning_tasks import focused, call
from tests.test_cleaning_loop import action


def clean_report(tmp_path):
    source = tmp_path / "input.csv"
    source.write_text("amount\n1\n2\n", encoding="utf-8")
    return {"dataset_ref": {"file_path": str(source), "file_name": source.name, "rows": 2, "columns": 1}}


def test_nested_runs_keep_their_own_manager_results_and_final_status(tmp_path):
    agent = DataCleaningAgent(data_root=tmp_path / "runs", use_llm=False)
    report = clean_report(tmp_path)
    nested = []
    def callback(event):
        if event.get("tool") and not nested:
            nested.append(agent.run(report))
    outer = agent.run(report, on_event=callback)
    inner = nested[0]
    assert outer.source_dataset.path != inner.source_dataset.path
    for result in (outer, inner):
        folder = Path(result.final_dataset.path).parent
        assert Path(result.metadata["result_path"]).parent == folder
        saved = json.loads((folder / "cleaning_result.json").read_text())
        trace = json.loads((folder / "execution_trace.json").read_text())
        meta = json.loads((folder / f"{result.final_dataset.version}_meta.json").read_text())
        assert saved["source_dataset"]["path"] == result.source_dataset.path
        assert trace["current_dataset"] == meta == result.final_dataset.model_dump(mode="json")
        assert trace["stop_reason"] == result.metadata["stop_reason"]


def test_callback_failure_does_not_abort_or_probe_unused_sandbox(tmp_path, monkeypatch, caplog):
    def fail(*args):
        raise RuntimeError("UI unavailable")
    monkeypatch.setattr("agents.dataCleaning_agent.sandbox_status", fail)
    result = DataCleaningAgent(data_root=tmp_path / "runs", use_llm=False).run(clean_report(tmp_path), on_event=fail)
    assert result.validation.all_passed
    assert "Progress callback failed" in caplog.text
    assert result.metadata["sandbox"] == {"required_backend": "docker", "executed_image_ids": []}


def test_snapshot_is_read_only_and_both_files_retry_transient_locks(focused, monkeypatch):
    state, _, _ = focused
    context = deepcopy(state.working_context)
    tasks = deepcopy(state.cleaning_tasks)
    def no_read(*args):
        raise AssertionError("Saving a snapshot must not reload or reclassify data")
    monkeypatch.setattr(state.manager, "load", no_read)
    replace = Path.replace
    attempts = {}
    def locked_once(path, target):
        name = Path(target).name
        attempts[name] = attempts.get(name, 0) + 1
        if attempts[name] == 1:
            raise PermissionError("Transient reader lock")
        return replace(path, target)
    monkeypatch.setattr(Path, "replace", locked_once)
    state.persist_trace()
    assert attempts == {"execution_trace.json": 2, "cleaning_context.json": 2}
    assert state.working_context == context and state.cleaning_tasks == tasks


def test_validation_uses_actual_data_instead_of_stale_task_status(focused):
    state, executor, _ = focused
    state.required_targets = {"amount": "float"}
    state.required_missing = []
    state.cleaning_tasks = [t for t in state.cleaning_tasks if t["columns"] == ["amount"] and t.get("measured") == "type_conversion"]
    assert state.cleaning_tasks[0]["status"] == "pending"
    frame = state.manager.load(state.current_ref)
    frame["amount"] = [10.0, 20.0]
    frame.to_csv(state.current_ref.path, index=False)
    assert executor._validate_dataset({})["success"]
    assert state.cleaning_tasks[0]["status"] == "done" and state.validation.all_passed


def test_stop_records_one_failure_without_persistence_side_effects(focused):
    state, _, _ = focused
    state.stop("provider_error", "Model unavailable")
    state.stop("provider_error", "Model unavailable")
    assert state.finished and state.stop_reason == "provider_error"
    assert state.unresolved == ["Model unavailable"]


@pytest.mark.parametrize("settings", [{"max_turns": 1.5}, {"max_turns": True}, {"max_turns": "3"},
    {"max_seconds": True}, {"max_seconds": "30"}, {"max_seconds": float("nan")}])
def test_invalid_budgets_fail_before_creating_a_run(tmp_path, settings):
    root = tmp_path / "runs"
    with pytest.raises(ValueError, match="budgets"):
        DataCleaningAgent(data_root=root, use_llm=False, **settings)
    assert not root.exists()


def test_context_errors_are_not_mislabeled_as_provider_failures(tmp_path, monkeypatch):
    def broken(*args):
        raise ValueError("Invalid task context")
    monkeypatch.setattr("agents.dataCleaning_agent.cleaning_tasks.model_view", broken)
    result = DataCleaningAgent(data_root=tmp_path / "runs", use_llm=True).run(clean_report(tmp_path))
    assert result.metadata["stop_reason"] == "controller_error"
    assert not result.metadata["provider_errors"]
    assert "Invalid task context" in result.metadata["finish_summary"]


def test_provider_retry_reuses_prepared_task_context(tmp_path, monkeypatch):
    from dataCleaningTools import cleaning_tasks
    original = cleaning_tasks.model_view
    prepared, requests = [], []
    def context(*args):
        prepared.append(1)
        return original(*args)
    class ToolError(Exception):
        status_code = 400
        body = {"error": {"code": "tool_use_failed"}}
    def respond(*args, **kwargs):
        requests.append(1)
        if len(requests) == 1:
            raise ToolError("Malformed provider tool call")
        return action("finish", summary="No cleaning needed")
    monkeypatch.setattr(cleaning_tasks, "model_view", context)
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", respond)
    result = DataCleaningAgent(data_root=tmp_path / "runs", use_llm=True).run(clean_report(tmp_path))
    assert result.validation.all_passed and len(requests) == 2 and len(prepared) == 1
    assert result.metadata["provider_errors"][0]["recovered"]


def test_noop_does_not_direct_finish_while_advisory_tasks_remain(focused):
    state, executor, _ = focused
    state.required_targets = {}
    state.required_missing = []
    state.cleaning_tasks = [t for t in state.cleaning_tasks if t["columns"] == ["region"]]
    for _ in range(2):
        trial = call(executor, "test_builtin", columns=["region"], operation="trim_whitespace", parameters={}, hypothesis="Trim observed whitespace")
        result = call(executor, "apply_candidate", candidate_id=trial["candidate_id"], assessment="Only whitespace changed")
        assert result["success"]
    assert result["no_op"]
    assert "Call finish" not in result["message"]
    assert "Call finish now" not in result["recovery_prompt"]["instruction"]
    assert state.cleaning_tasks[0]["status"] == "pending"


def test_stopped_session_cannot_commit_more_transformations(focused):
    state, executor, _ = focused
    before = Path(state.current_ref.path).read_bytes()
    state.stop("provider_error", "Model unavailable")
    result = json.loads(executor.execute_trusted("trim_whitespace", {"columns": ["region"]}))
    assert not result["success"] and "Run is finished" in result["error"]
    assert Path(state.current_ref.path).read_bytes() == before and state.current_ref.version == "V1"
    assert not state.manager.get_changelog(state.dataset_id).entries



def test_prompt_budget_groups_failures_without_mutating_audit_or_breaking_tool_pairs(monkeypatch):
    from copy import deepcopy
    from agents.dataCleaning_agent import _request_context
    monkeypatch.setenv("BIFLOW_OLLAMA_NUM_CTX", "3000")
    monkeypatch.setenv("BIFLOW_OLLAMA_NUM_PREDICT", "1000")
    messages = [{"role": "system", "content": "Policy"}, {"role": "user", "content": "Objective"},
        {"role": "assistant", "tool_calls": [{"id": "trial", "function": {"name": "test_generated", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "trial", "content": json.dumps({"success": False,
            "lost_values": [{"row_position": i, "before": "one", "expected": 1, "actual": None} for i in range(500)]})}]
    original = deepcopy(messages)
    sent = _request_context(messages, tools=[], reserved_chars=100)
    assert messages == original and len(json.dumps(sent)) + 100 + 2 <= 8000
    assert sent[-1]["tool_call_id"] == sent[-2]["tool_calls"][0]["id"]
    feedback = json.loads(sent[-1]["content"])
    assert feedback["success"] is False and feedback["lost_values"]["total_cells"] == 500
    assert feedback["lost_values"]["groups"][0]["expected"] == 1


def test_prompt_budget_refuses_oversized_code_without_truncating_it(monkeypatch):
    from agents.dataCleaning_agent import _request_context
    monkeypatch.setenv("BIFLOW_OLLAMA_NUM_CTX", "2000")
    monkeypatch.setenv("BIFLOW_OLLAMA_NUM_PREDICT", "1000")
    messages = [{"role": "system", "content": "Policy"}, {"role": "user", "content": "Objective"},
                {"role": "assistant", "content": "code" * 2000}]
    with pytest.raises(ValueError, match="no request sent"):
        _request_context(messages, tools=[])
    assert len(messages[-1]["content"]) == 8000
