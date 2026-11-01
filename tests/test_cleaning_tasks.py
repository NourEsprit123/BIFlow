import json
from copy import deepcopy

import pandas as pd
import pytest

from dataCleaningTools import cleaning_tasks, experiments
from dataCleaningTools.models import ProfilingReport
from dataCleaningTools.tool_registry import AgentSessionState, ToolExecutor
from dataCleaningTools.versioning import DatasetVersionManager
from dataCleaningTools.working_context import initialize as initialize_context
from tests.test_cleaning_loop import action


@pytest.fixture
def focused(tmp_path):
    path = tmp_path / "input.csv"
    pd.DataFrame({"amount": ["$10", None], "flag": ["Yes", "No"], "region": ["North ", "South"]}).to_csv(path, index=False)
    report = ProfilingReport.model_validate({"dataset_ref": {"file_path": str(path), "file_name": path.name, "rows": 2, "columns": 3},
        "column_profiles": {"amount": {"etl_cast_to": "float", "missing_count": 1}, "flag": {"etl_cast_to": "boolean"},
                            "region": {"issues": [{"issue_id": "whitespace", "description": "Trailing spaces"}]}},
        "outlier_columns": ["amount"], "cross_column_issues": [{"columns": ["amount", "flag"], "description": "Meaning needs confirmation"}]})
    manager = DatasetVersionManager(tmp_path / "versions")
    source = manager.register_original(path, dataset_id="input")
    state = AgentSessionState(manager=manager, dataset_id="input", source_ref=source, current_ref=manager.create_working_copy(source),
        required_targets={"amount": "float", "flag": "boolean"}, required_missing=["amount"], expected_columns=list(source.columns))
    initialize_context(state, report)
    original = deepcopy(state.working_report)
    state.focused_cleaning = True
    cleaning_tasks.initialize(state)
    return state, ToolExecutor(state), original


def call(executor, name, **args):
    return json.loads(executor.execute(name, args))


def review_formatting(state, executor):
    call(executor, "inspect_data", view="column", column="region", reason="Verify whitespace",
         question="What raw labels support retaining or trimming whitespace?", expected_evidence="Column examples and counts")
    return call(executor, "complete_task", task_id=cleaning_tasks.active(state)["id"], disposition="reviewed",
                reason="Inspected; retaining these labels pending canonical naming policy")


def test_tasks_are_small_ordered_and_do_not_edit_agent1(focused):
    state, executor, original = focused
    assert [(t["category"], t["columns"]) for t in state.cleaning_tasks] == [
        ("formatting", ["region"]), ("types", ["amount"]), ("types", ["flag"]),
        ("missing", ["amount"]), ("outliers", ["amount"]), ("domain", ["amount", "flag"])]
    view = cleaning_tasks.model_view(state, executor)
    assert list(view["working_context"]["columns"]) == ["region"]
    assert "pending_missing" not in view["outstanding"]
    assert view["cleaning_focus"]["category"] == "formatting"
    assert state.working_report == original
    categories = {c["category"]: c["status"] for c in cleaning_tasks.summary(state)}
    assert categories["duplicates"] == "no_reported_findings"
    assert categories["understanding"] == "consumed_profiling_report"


def test_information_is_not_a_repair_but_actual_requirements_remain(focused):
    state, _, _ = focused
    state.working_report["column_profiles"]["Order_ID"] = {"issues": [{
        "issue_id": "type_mismatch", "severity": "NONE", "description": "Pseudo-ID; 100% valid"}]}
    # Low-severity and unspecified findings still require assessment.
    state.working_report["column_profiles"]["region"]["issues"] += [
        {"issue_id": "invalid_value", "severity": "LOW", "description": "Check labels"},
        {"issue_id": "category_format", "description": "Investigate case"}]
    state.working_report["column_profiles"]["amount"]["issues"] = [
        {"issue_id": "type_mismatch", "severity": "INFO", "description": "Informational note"}]
    state.working_report["cross_column_issues"].append({
        "columns": ["Order_ID"], "severity": "INFORMATIONAL", "description": "Join key"})
    report_before = deepcopy(state.working_report)
    cleaning_tasks.initialize(state)
    assert not any("Order_ID" in t["columns"] for t in state.cleaning_tasks)
    assert any(t["columns"] == ["amount"] and t.get("measured") == "type_conversion" for t in state.cleaning_tasks)
    assert any(t["columns"] == ["amount"] and t.get("measured") == "missing_values" for t in state.cleaning_tasks)
    assert any(e.get("severity") == "LOW" for t in state.cleaning_tasks for e in t["evidence"])
    assert any(e.get("issue_id") == "category_format" for t in state.cleaning_tasks for e in t["evidence"])
    assert state.working_report == report_before


def test_scope_and_completion_cannot_skip_dataset_checks(focused):
    state, executor, _ = focused
    task_id = cleaning_tasks.active(state)["id"]
    assert not call(executor, "complete_task", task_id=task_id, disposition="reviewed", reason="Looks fine")["success"]
    assert not call(executor, "test_builtin", columns=["amount", "region"], hypothesis="Clean all", operation="trim_whitespace", parameters={})["success"]
    # A useful inspection resets the counter; three consecutive invalid requests
    # now intentionally defer a task, rather than leaving it pending indefinitely.
    call(executor, "inspect_data", view="patterns", column="region", reason="Check current label syntax")
    assert not call(executor, "inspect_data", view="column", column="amount", reason="Other column")["success"]
    assert review_formatting(state, executor)["success"]
    task = cleaning_tasks.active(state)
    assert task["category"] == "types" and task["columns"] == ["amount"]
    assert not call(executor, "complete_task", task_id=task["id"], disposition="reviewed", reason="I say converted")["success"]
    assert not call(executor, "test_builtin", columns=["amount"], hypothesis="Fill first", operation="handle_missing_values", parameters={"strategy": "fill_constant", "fill_value": 0})["success"]
    result = call(executor, "test_builtin", columns=["amount"], hypothesis="Remove currency symbol", operation="clean_numeric_string", parameters={})
    assert result["tested"]
    assert cleaning_tasks.active(state)["id"] == task["id"]  # uncommitted copy is insufficient
    assert call(executor, "apply_candidate", candidate_id=result["candidate_id"], assessment="Full copy preserved all values")["success"]
    assert cleaning_tasks.active(state)["columns"] == ["flag"]
    assert pd.isna(state.manager.load(state.current_ref)["amount"].iloc[1])


def test_pending_advisories_and_review_assessments_reach_validation(focused):
    state, executor, _ = focused
    state.required_targets = {}; state.required_missing = []
    initialize_context(state, ProfilingReport.model_validate(state.working_report))
    state.cleaning_tasks = [t for t in state.cleaning_tasks if not t.get("measured")]
    assert not call(executor, "finish", summary="All fine", unresolved=[])["success"]
    while cleaning_tasks.active(state):
        task = cleaning_tasks.active(state)
        assert call(executor, "complete_task", task_id=task["id"], disposition="needs_review", reason="Business policy required")["success"]
    result = call(executor, "finish", summary="Technical checks passed; policy needed", unresolved=[])
    assert result["success"] and result["validation"]["status"] == "partial"
    assert any("Business policy required" in text for text in result["exceptions"])
    assert not call(executor, "test_builtin", columns=["region"], hypothesis="Another repair", operation="trim_whitespace", parameters={})["success"]


def test_generated_conversion_does_not_require_imputation(focused, monkeypatch):
    state, executor, _ = focused
    review_formatting(state, executor)
    seen = []
    def runner(frame, code, **kwargs):
        output = frame.copy()
        output["amount"] = pd.to_numeric(output["amount"].str.replace("$", "", regex=False))
        seen.append(output)
        return {"success": True, "df": output, "repeatable": True, "image_id": "sha256:test"}
    monkeypatch.setattr(experiments, "run_isolated_transform", runner)
    result = call(executor, "test_generated", columns=["amount"], hypothesis="Parse currency; preserve existing null",
        code="def transform(df):\n    return df", checks=[{"column": "amount", "kind": "numeric"}])
    assert result["tested"], result
    checks = state.method_candidates[result["candidate_id"]]["checks"]
    assert {"column": "amount", "kind": "no_missing"} not in checks
    assert seen


def test_agent_resets_old_task_context_and_rejects_batched_actions(tmp_path, monkeypatch):
    from agents.dataCleaning_agent import DataCleaningAgent
    source = tmp_path / "input.csv"
    pd.DataFrame({"first": ["Yes", "No"], "second": ["Yes", "No"]}).to_csv(source, index=False)
    payload = {"dataset_ref": {"file_path": str(source), "file_name": source.name, "rows": 2, "columns": 2},
               "column_profiles": {c: {"etl_cast_to": "boolean"} for c in ["first", "second"]}}
    calls = []
    def respond(messages, tools, **kwargs):
        context = json.loads(messages[-1]["content"])
        calls.append(context)
        if len(calls) == 3:
            return action("finish", summary="Both flags verified")
        column = ["first", "second"][len(calls)-1]
        assert list(context["working_context"]["columns"]) == [column]
        if column == "second":
            assert not any(m["role"] == "tool" for m in messages)
        response = action("test_builtin", columns=[column], hypothesis="Observed Yes/No", operation="convert_data_types", parameters={"target_type": "boolean"})
        if column == "first":
            response["tool_calls"] += action("flag_for_review", columns=["second"], reason="Skip it")["tool_calls"]
        return response
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", respond)
    result = DataCleaningAgent(data_root=tmp_path/"versions", use_llm=True).run(payload)
    assert result.validation.all_passed
    assert not result.metadata["flagged"]
    assert all(t["status"] == "done" for t in result.metadata["cleaning_tasks"])
    assert [e["task_id"] for e in result.metadata["events"] if e["tool"] == "test_builtin"] == ["task-1", "task-2"]


def test_parser_that_also_imputes_is_rejected(focused, monkeypatch):
    state, executor, _ = focused
    review_formatting(state, executor)
    def runner(frame, code, **kwargs):
        output = frame.copy()
        output["amount"] = pd.to_numeric(output["amount"].str.replace("$", "", regex=False)).fillna(0)
        return {"success": True, "df": output, "repeatable": True, "image_id": "sha256:test"}
    monkeypatch.setattr(experiments, "run_isolated_transform", runner)
    result = call(executor, "test_generated", columns=["amount"], hypothesis="Parser must not impute at this stage",
        code="def transform(df):\n    return df", checks=[{"column": "amount", "kind": "numeric"}])
    assert not result["tested"] and state.current_ref.version == "V1"
    assert any(not rule["passed"] and rule["rule_name"] == "expected:preserve_missing:amount"
               for trial in result["trials"] if trial.get("effect") for rule in trial["effect"]["rules"])


def test_model_view_refreshes_before_selecting_task_and_loads_once(focused, monkeypatch):
    state, executor, _ = focused
    review_formatting(state, executor)
    frame = state.manager.load(state.current_ref)
    frame["amount"] = [10.0, 20.0]
    frame.to_csv(state.current_ref.path, index=False)
    load, reads = state.manager.load, []
    def tracked(ref):
        reads.append(ref.version)
        return load(ref)
    monkeypatch.setattr(state.manager, "load", tracked)
    view = cleaning_tasks.model_view(state, executor)
    assert view["cleaning_focus"]["task"]["columns"] == ["flag"]
    assert list(view["working_context"]["columns"]) == ["flag"]
    assert view["value_interpretation"]["columns"]["flag"]["mappings"]
    assert reads == ["V1"]


def test_review_reopens_only_after_changes_to_its_columns(focused):
    state, executor, _ = focused
    review_formatting(state, executor)
    task = next(t for t in state.cleaning_tasks if t["columns"] == ["region"])
    change = json.loads(executor.execute_trusted("normalize_values", {"column": "region", "case": "upper"}))
    assert change["success"] and task["status"] == "pending" and task["reopened_version"] == "V2"
    # Old inspection results cannot justify a new review after the column changed.
    assert not call(executor, "complete_task", task_id=task["id"], disposition="reviewed", reason="Reuse old evidence")["success"]
    assert review_formatting(state, executor)["success"]
    assert task["assessed_version"] == "V2"
    assert json.loads(executor.execute_trusted("convert_data_types", {"column": "flag", "target_type": "boolean"}))["success"]
    assert task["status"] == "reviewed" and task["assessed_version"] == "V2"


def test_requirement_changes_sync_without_duplicate_tasks(focused):
    from dataCleaningTools.working_context import refresh
    state, _, _ = focused
    state.required_targets["region"] = "string"
    state.required_missing += ["amount", "region"]
    refresh(state)
    count = len(state.cleaning_tasks)
    refresh(state)
    assert len(state.cleaning_tasks) == count
    assert len({t["id"] for t in state.cleaning_tasks}) == count
    assert any(t["columns"] == ["region"] and t.get("measured") == "type_conversion" and t["status"] == "done" for t in state.cleaning_tasks)
    state.required_targets.pop("amount")
    state.required_missing = ["region"]
    refresh(state)
    obsolete = [t for t in state.cleaning_tasks if t["columns"] == ["amount"] and t.get("measured")]
    assert obsolete and all(t["status"] == "not_required" for t in obsolete)


def test_cross_column_order_does_not_duplicate_a_task(focused):
    state, _, _ = focused
    state.working_report["cross_column_issues"].append({"columns": ["flag", "amount", "flag"], "description": "Another observation"})
    before = deepcopy(state.working_report)
    cleaning_tasks.initialize(state)
    tasks = [t for t in state.cleaning_tasks if t["category"] == "domain"]
    assert len(tasks) == 1 and len(tasks[0]["evidence"]) == 2
    assert state.working_report == before


def test_valid_dtype_does_not_resolve_an_invalid_value_finding(focused):
    state, _, _ = focused
    state.required_targets["region"] = "string"
    state.working_report["column_profiles"]["region"]["issues"].append({
        "issue_id": "invalid_value", "severity": "HIGH", "description": "Unexpected region code"})
    from dataCleaningTools.working_context import refresh
    refresh(state)
    cleaning_tasks.initialize(state)
    tasks = [t for t in state.cleaning_tasks if t["category"] == "types" and t["columns"] == ["region"]]
    assert any(t.get("measured") == "type_conversion" and t["status"] == "done" for t in tasks)
    assert any(t.get("measured") is None and t["status"] == "pending" for t in tasks)
    assert not cleaning_tasks.informational({"severity": None})


def test_unscoped_finding_has_a_valid_inspection_example(focused):
    state, _, _ = focused
    state.required_targets = {}
    state.required_missing = []
    state.working_report = {"cross_column_issues": [{"columns": None, "description": "Business rule needs clarification"}]}
    cleaning_tasks.initialize(state)
    guide = cleaning_tasks.request_guide(state, "")
    assert '"view": "schema"' in guide and '"column": ""' not in guide


def test_explicit_uncertainty_is_not_lost_from_the_task_queue(focused):
    state, _, _ = focused
    state.working_report["uncertainty_flags"] = [{"column": "region", "description": "Meaning is uncertain", "severity": None}]
    cleaning_tasks.initialize(state)
    assert any(t["category"] == "domain" and t["columns"] == ["region"] and t["status"] == "pending"
               for t in state.cleaning_tasks)
