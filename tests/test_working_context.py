import json
from pathlib import Path

import pandas as pd
import pytest

from agents.dataCleaning_agent import DataCleaningAgent
from dataCleaningTools.models import ProfilingReport
from dataCleaningTools.tool_registry import AgentSessionState, ToolExecutor
from dataCleaningTools.versioning import DatasetVersionManager
from dataCleaningTools.working_context import initialize, model_context, refresh


@pytest.fixture
def tracked(tmp_path):
    source = tmp_path / "input.csv"
    pd.DataFrame({"flag": ["Yes", "No"], "amount": [10.0, None]}).to_csv(source, index=False)
    payload = {"dataset_ref": {"file_path": str(source), "file_name": source.name, "rows": 2, "columns": 2},
        "column_profiles": {
            "flag": {"dtype": "str", "etl_cast_to": "boolean", "issues": [
                {"issue_id": "type_mismatch", "description": "Original text flag"},
                {"issue_id": "semantic", "description": "Business meaning needs evaluation"}]},
            "amount": {"dtype": "float64", "missing_count": 1,
                       "issues": [{"issue_id": "missing_values", "description": "Missing charge"}]}}}
    report_file = tmp_path / "report.json"
    report_file.write_text(json.dumps(payload), encoding="utf-8")
    report = ProfilingReport.model_validate(payload)
    manager = DatasetVersionManager(tmp_path / "versions")
    original = manager.register_original(source, dataset_id="input")
    state = AgentSessionState(manager=manager, dataset_id="input", source_ref=original,
        current_ref=manager.create_working_copy(original), required_targets={"flag": "boolean"},
        required_missing=["amount"], expected_columns=["flag", "amount"])
    initialize(state, report)
    state.persist_trace()
    return state, ToolExecutor(state), report, report_file


def call(executor, name, **args):
    return json.loads(executor.execute(name, args))


def flag_trial(executor):
    return call(executor, "test_builtin", hypothesis="Observed Yes/No flags encode binary values",
        columns=["flag"], operation="convert_data_types", parameters={"target_type": "boolean"})


def test_only_committed_checks_complete_steps_and_original_report_is_unchanged(tracked):
    state, executor, report, report_file = tracked
    original_model = report.model_dump(mode="json")
    original_bytes = report_file.read_bytes()
    trial = flag_trial(executor)
    assert trial["tested"]
    assert model_context(state)["columns"]["flag"]["steps"]["type_conversion"]["status"] == "pending"
    assert not state.working_context["completed_actions"]
    assert call(executor, "apply_candidate", candidate_id=trial["candidate_id"],
                assessment="Trial preserved values and passed its boolean check")["success"]
    context = model_context(state)
    assert context["columns"]["flag"]["steps"]["type_conversion"] == {
        "target": "boolean", "status": "done", "verified_version": "V2", "completed_version": "V2"}
    assert context["columns"]["amount"]["steps"]["missing_values"]["status"] == "pending"
    assert [o["description"] for o in context["columns"]["flag"]["observations"]] == ["Business meaning needs evaluation"]
    assert state.working_context["completed_actions"][0]["columns"] == ["flag"]
    saved = json.loads((state.manager.root / "input" / "cleaning_context.json").read_text())
    assert saved["profiling_report_copy"] == original_model
    assert saved["progress"]["columns"]["flag"]["steps"]["type_conversion"]["status"] == "done"
    assert report.model_dump(mode="json") == original_model and report_file.read_bytes() == original_bytes


def test_failed_trial_does_not_complete_steps(tracked):
    state, executor, _, _ = tracked
    assert not call(executor, "test_builtin", hypothesis="Attempt numeric conversion",
        columns=["flag"], operation="convert_data_types", parameters={"target_type": "float", "errors": "raise"})["success"]
    assert model_context(state)["columns"]["flag"]["steps"]["type_conversion"]["status"] == "pending"
    assert not state.working_context["completed_actions"]


def test_duplicate_conversion_uses_progress_feedback_not_parser_failure(tracked):
    _, executor, _, _ = tracked
    first = flag_trial(executor)
    call(executor, "apply_candidate", candidate_id=first["candidate_id"], assessment="Trial passed")
    assert flag_trial(executor)["tested"]  # one no-op trial on the new version
    duplicate = flag_trial(executor)
    assert not duplicate["success"]
    assert duplicate["recovery_prompt"]["case"] == "duplicate_method"


def test_review_is_not_completion_and_regressions_reopen_steps(tracked):
    state, executor, _, _ = tracked
    trial = flag_trial(executor)
    call(executor, "apply_candidate", candidate_id=trial["candidate_id"], assessment="Trial passed")
    frame = state.manager.load(state.current_ref)
    frame["flag"] = ["Yes", "No"]
    frame.to_csv(state.current_ref.path, index=False)
    refresh(state)
    assert model_context(state)["columns"]["flag"]["steps"]["type_conversion"]["status"] == "pending"
    call(executor, "flag_for_review", columns=["flag"], reason="Meaning uncertain")
    step = model_context(state)["columns"]["flag"]["steps"]["type_conversion"]
    assert step["status"] == "needs_review" and "completed_version" not in step


def test_run_context_survives_history_trimming_and_new_runs_start_fresh(tracked, tmp_path, monkeypatch):
    _, _, report, report_file = tracked
    original = report_file.read_bytes()
    monkeypatch.setattr("agents.dataCleaning_agent.sandbox_status", lambda: {})
    requests = []
    def respond(messages, tools, **kwargs):
        requests.append(messages)
        context = json.loads(messages[-1]["content"])["working_context"]
        turn = len(requests)
        if turn == 1:
            assert context["columns"]["flag"]["steps"]["type_conversion"]["status"] == "pending"
            name, args = "test_builtin", {"hypothesis": "Observed binary encoding", "columns": ["flag"],
                "operation": "convert_data_types", "parameters": {"target_type": "boolean"}}
        elif turn < 6:
            name, args = "inspect_data", {"reason": "Inspect charge distribution before choosing imputation",
                                         "view": {2: "column", 3: "patterns", 4: "distribution", 5: "extremes"}[turn], "column": "amount",
                                         "question": f"Inspect additional distribution aspect {turn}",
                                         "expected_evidence": "Previously unseen counts, patterns or extremes"}
        else:
            assert not any(m.get("tool_calls", [{}])[0].get("function", {}).get("name") == "test_builtin"
                           for m in messages if m.get("tool_calls"))
            assert context["completed_actions"][0]["columns"] == ["flag"]
            if turn == 6:
                assert list(context["columns"]) == ["amount"]
                assert context["columns"]["amount"]["steps"]["missing_values"]["status"] == "pending"
                name, args = "flag_for_review", {"columns": ["amount"], "reason": "Imputation requires a business decision"}
        if turn == 7:
            focus = json.loads(messages[-1]["content"])["cleaning_focus"]
            assert focus["category"] == "domain" and focus["task"]["columns"] == ["flag"]
            name, args = "complete_task", {"task_id": focus["task"]["id"], "disposition": "needs_review", "reason": "Business meaning needs confirmation"}
        if turn == 8:
            name, args = "finish", {"summary": "Flag converted; charge imputation needs review"}
        return {"tool_calls": [{"id": str(turn), "name": name, "arguments": args}]}
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", respond)
    agent = DataCleaningAgent(data_root=tmp_path / "runs", use_llm=True)
    result = agent.run(report)
    assert len(requests) == 8 and result.validation.status.value == "partial"
    assert Path(result.metadata["working_context_path"]).is_file()
    assert report_file.read_bytes() == original
    dry = DataCleaningAgent(data_root=tmp_path / "runs", dry_run=True).run(report)
    assert dry.metadata["working_context_path"] != result.metadata["working_context_path"]
    assert dry.metadata["working_context"]["columns"]["flag"]["steps"]["type_conversion"]["status"] == "pending"


def test_projection_does_not_read_data_or_change_memory(tracked, monkeypatch):
    from copy import deepcopy
    state, _, report, _ = tracked
    before = deepcopy(state.working_context)
    def forbidden(*args):
        raise AssertionError("Projecting memory must not reload the dataset")
    monkeypatch.setattr(state.manager, "load", forbidden)
    view = model_context(state, ["flag"])
    view["columns"]["flag"]["steps"].clear()
    assert state.working_context == before
    state.working_report["column_profiles"]["flag"]["issues"][0]["description"] = "Local copy"
    assert report.column_profiles["flag"].issues[0].description == "Original text flag"


def test_memory_keeps_actual_examples_after_conversion(tracked):
    state, executor, _, _ = tracked
    trial = flag_trial(executor)
    call(executor, "apply_candidate", candidate_id=trial["candidate_id"], assessment="Verified flag conversion")
    view = model_context(state)["columns"]["flag"]
    assert view["current_examples"] == ["True", "False"]
    assert "source_examples" not in view


def test_memory_tracks_unprofiled_columns_and_single_column_host_changes(tracked):
    state, executor, _, _ = tracked
    state.working_report["column_profiles"].pop("amount")
    refresh(state)
    assert state.working_context["columns"]["amount"]["missing_count"] == 1
    result = json.loads(executor.execute_trusted("convert_data_types", {"column": "flag", "target_type": "boolean"}))
    assert result["success"]
    assert state.working_context["completed_actions"][-1]["columns"] == ["flag"]


def test_new_target_does_not_reuse_old_completion_version(tracked):
    state, _, _, _ = tracked
    state.required_targets["amount"] = "float"
    refresh(state)
    assert state.working_context["columns"]["amount"]["steps"]["type_conversion"]["completed_version"] == "V1"
    state.current_ref = state.manager.create_working_copy(state.current_ref)
    state.required_targets["amount"] = "integer"
    refresh(state)
    step = state.working_context["columns"]["amount"]["steps"]["type_conversion"]
    assert step["status"] == "done" and step["completed_version"] == "V2"


def test_nested_projection_values_do_not_alias_memory(tracked):
    state, executor, _, _ = tracked
    trial = flag_trial(executor)
    call(executor, "apply_candidate", candidate_id=trial["candidate_id"], assessment="Verified flag")
    state.working_report["imputation_plan"] = {"amount": {"strategy": "median"}}
    view = model_context(state)
    view["completed_actions"][0]["columns"].append("not_a_real_column")
    view["columns"]["amount"]["suggested_imputation"]["strategy"] = "changed"
    assert state.working_context["completed_actions"][0]["columns"] == ["flag"]
    assert state.working_report["imputation_plan"]["amount"]["strategy"] == "median"
