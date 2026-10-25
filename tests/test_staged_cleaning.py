import json
from pathlib import Path

import pandas as pd
import pytest

from agents.dataCleaning_agent import DataCleaningAgent
from dataCleaningTools import cleaning, experiments, workflow
from dataCleaningTools.models import ProfilingReport
from dataCleaningTools.tool_registry import AgentSessionState, ToolExecutor
from dataCleaningTools.versioning import DatasetVersionManager


CODE = "def transform(df):\n    df['Revenue'] = pd.to_numeric(df['Revenue'].str.replace(r'[^0-9.]', '', regex=True))\n    return df\n"


@pytest.fixture
def staged(tmp_path):
    source = tmp_path / "sales.csv"
    pd.DataFrame({"Revenue": ["$10", "USD 20", "$30", "USD 40"], "name": ["a", "b", "c", "d"]}).to_csv(source, index=False)
    manager = DatasetVersionManager(tmp_path / "versions")
    original = manager.register_original(source, dataset_id="sales")
    state = AgentSessionState(manager=manager, dataset_id="sales", source_ref=original,
        current_ref=manager.create_working_copy(original), required_targets={"Revenue": "float"}, expected_columns=["Revenue", "name"])
    report = {"dataset_ref": {"file_path": str(source), "file_name": source.name, "rows": 4, "columns": 2},
              "column_profiles": {"Revenue": {"dtype": "str", "etl_cast_to": "float"}}}
    workflow.initialize(state, ProfilingReport.model_validate(report))
    return state, ToolExecutor(state), report


def proposal(kind="builtin", **changes):
    args = {"issue_ids": ["type:Revenue"], "hypothesis": "Revenue is numeric text with currency labels",
        "assumptions": ["All four observed values use the same unit"],
        "rationale": "Inspect currency text before parsing", "expected_effect": "Parse values without introducing missing data",
        "evidence_ids": ["profile:Revenue"], "columns": ["Revenue"], "kind": kind,
        "checks": [{"column": "Revenue", "kind": "numeric"}]}
    if kind == "builtin":
        args.update(operation="convert_data_types", parameters={"column": "Revenue", "target_type": "float", "errors": "coerce"})
    else:
        args["code"] = CODE
    return {**args, **changes}


def call(executor, name, **args):
    return json.loads(executor.execute(name, args))


def runner(calls, fail_full=False):
    # A trusted test implementation; never execute generated code on the host.
    def run(frame, code, *, image_id=None):
        calls.append((len(frame), code, image_id))
        after = frame.copy()
        after["Revenue"] = pd.to_numeric(after.Revenue.str.replace(r"[^0-9.]", "", regex=True))
        if fail_full and len(frame) == 4:
            after.loc[after.index[0], "Revenue"] = None
        return {"success": True, "df": after, "image_id": "sha256:test", "repeatable": True}
    return run


def accept(executor, candidate_id):
    return call(executor, "review_candidate", candidate_id=candidate_id, decision="accept",
                assessment="Trials satisfy the numeric expectation without missing values or changes to unrelated columns")


def test_small_interface_and_stage_prompts(staged):
    state, executor, _ = staged
    assert {t["function"]["name"] for t in workflow.WORKFLOW_SCHEMAS} == {
        "inspect_data", "test_method", "review_candidate", "apply_candidate", "request_review", "finish"}
    assert "Issue ledger" in workflow.stage_context(state)
    assert "convert_data_types" in workflow.stage_context(state)
    result = call(executor, "inspect_data", view="patterns", column="Revenue")
    assert result["event_id"] in state.evidence and state.workflow_stage == "propose"
    assert state.current_ref.version == "V1"


def test_failed_builtin_is_evidence_for_a_generated_revision(staged, monkeypatch):
    state, executor, _ = staged
    original = Path(state.source_ref.path).read_bytes()
    failed = call(executor, "test_method", **proposal())
    assert not failed["tested"] and failed["revision_feedback"]["trials"]
    assert state.current_ref.version == "V1" and state.workflow_stage == "revise"
    assert not accept(executor, failed["candidate_id"])["success"]
    assert not call(executor, "test_method", **proposal())["success"]
    calls = []
    monkeypatch.setattr(experiments, "run_isolated_transform", runner(calls))
    revised = call(executor, "test_method", **proposal("generated"))
    assert revised["tested"] and state.workflow_stage == "evaluate"
    assert not call(executor, "apply_candidate", candidate_id=revised["candidate_id"])["success"]
    assert accept(executor, revised["candidate_id"])["success"]
    applied = call(executor, "apply_candidate", candidate_id=revised["candidate_id"])
    assert applied["success"] and applied["validation"]["success"]
    assert state.workflow_stage == "conclude" and len(calls) == 3
    assert state.issues["type:Revenue"]["status"] == "resolved"
    assert Path(state.source_ref.path).read_bytes() == original
    assert state.manager.load(state.current_ref).Revenue.tolist() == [10, 20, 30, 40]


def test_full_data_failure_returns_measured_feedback_and_preserves_version(staged, monkeypatch):
    state, executor, _ = staged
    monkeypatch.setattr(experiments, "run_isolated_transform", runner([], fail_full=True))
    candidate = call(executor, "test_method", **proposal("generated"))
    assert candidate["tested"]
    accept(executor, candidate["candidate_id"])
    applied = call(executor, "apply_candidate", candidate_id=candidate["candidate_id"])
    assert not applied["success"] and state.current_ref.version == "V1"
    assert applied["revision_feedback"]["failed_checks"] and state.workflow_stage == "revise"
    assert state.issues["type:Revenue"]["failed_trials"] == 1
    # A genuinely revised candidate can recover without a permanent stale error.
    monkeypatch.setattr(experiments, "run_isolated_transform", runner([]))
    revised = call(executor, "test_method", **proposal("generated", code=CODE + "\n# revised parser\n"))
    accept(executor, revised["candidate_id"])
    assert call(executor, "apply_candidate", candidate_id=revised["candidate_id"])["validation"]["success"]


def test_builtin_full_checks_are_not_replaced_by_trial_success(staged, monkeypatch):
    state, executor, _ = staged
    before = cleaning.clean_numeric_string
    def full_loss(frame, **kwargs):
        outcome = before(frame, **kwargs)
        if len(frame) == 4 and outcome.success:
            outcome.df.loc[frame.index[0], "Revenue"] = None
        return outcome
    # Use a known all-numeric input so the test targets full-data checking.
    frame = state.manager.load(state.current_ref)
    frame["Revenue"] = ["$10", "$20", "$30", "$40"]
    frame.to_csv(state.current_ref.path, index=False)
    monkeypatch.setattr(cleaning, "clean_numeric_string", full_loss)
    candidate = call(executor, "test_method", **proposal(operation="clean_numeric_string", parameters={"column": "Revenue"}))
    assert candidate["tested"]
    accept(executor, candidate["candidate_id"])
    result = call(executor, "apply_candidate", candidate_id=candidate["candidate_id"])
    assert not result["success"] and state.current_ref.version == "V1"
    assert result["revision_feedback"]["failed_checks"]


@pytest.mark.parametrize("change", ["method", "data"])
def test_candidate_must_remain_unchanged(staged, monkeypatch, change):
    state, executor, _ = staged
    monkeypatch.setattr(experiments, "run_isolated_transform", runner([]))
    candidate = call(executor, "test_method", **proposal("generated"))
    accept(executor, candidate["candidate_id"])
    if change == "method":
        state.method_candidates[candidate["candidate_id"]]["checks"] = []
    else:
        Path(state.current_ref.path).write_text("Revenue,name\n$99,z\n", encoding="utf-8")
    assert not call(executor, "apply_candidate", candidate_id=candidate["candidate_id"])["success"]
    assert state.current_ref.version == "V1"


def test_ambiguous_decision_is_not_experimented_around(staged):
    state, executor, _ = staged
    result = call(executor, "request_review", issue_ids=["type:Revenue"], reason="Currency units are undocumented")
    assert result["approval_required"]
    assert not call(executor, "test_method", **proposal())["success"]
    assert not call(executor, "finish", summary="Awaiting currency definition")["success"]
    assert state.issues["type:Revenue"]["status"] == "awaiting_review"


def test_issue_failure_budget_is_bounded(staged):
    state, executor, _ = staged
    for mode in ["coerce", "raise", "ignore"]:
        result = call(executor, "test_method", **proposal(parameters={"column": "Revenue", "target_type": "float", "errors": mode}))
        assert not result["success"]
    assert state.issues["type:Revenue"]["failed_trials"] == 3
    result = call(executor, "test_method", **proposal("generated"))
    assert "three failed trials" in result["error"]


def test_builtin_boolean_method_is_tested_reviewed_and_applied(staged):
    state, executor, _ = staged
    frame = state.manager.load(state.current_ref)
    frame["Revenue"] = ["Yes", "No", "Yes", "No"]
    frame.to_csv(state.current_ref.path, index=False)
    state.required_targets["Revenue"] = "boolean"
    state.issues["type:Revenue"]["target"] = "boolean"
    candidate = call(executor, "test_method", **proposal(
        parameters={"column": "Revenue", "target_type": "boolean", "errors": "raise"},
        checks=[{"column": "Revenue", "kind": "boolean"}]))
    assert candidate["tested"] and state.current_ref.version == "V1"
    assert not call(executor, "apply_candidate", candidate_id=candidate["candidate_id"])["success"]
    accept(executor, candidate["candidate_id"])
    result = call(executor, "apply_candidate", candidate_id=candidate["candidate_id"])
    assert result["validation"]["success"]
    assert state.manager.load(state.current_ref).Revenue.tolist() == [True, False, True, False]


def test_noop_cannot_resolve_an_unverified_profiling_finding(staged):
    state, executor, _ = staged
    state.required_targets.clear()
    state.issues = {"finding:Revenue:0": {"column": "Revenue", "kind": "finding", "status": "pending", "failed_trials": 0}}
    candidate = call(executor, "test_method", **proposal(
        issue_ids=["finding:Revenue:0"], operation="trim_whitespace", parameters={"columns": ["Revenue"]},
        checks=[{"column": "Revenue", "kind": "string"}]))
    assert candidate["tested"]
    accept(executor, candidate["candidate_id"])
    result = call(executor, "apply_candidate", candidate_id=candidate["candidate_id"])
    assert result["no_op"] and result["revision_feedback"]
    assert state.issues["finding:Revenue:0"]["status"] == "pending"
    assert not result["validation"]["success"] and state.current_ref.version == "V1"


def test_llm_receives_explicit_error_prompt_and_revises_to_sandbox(staged, tmp_path, monkeypatch):
    _, _, report = staged
    monkeypatch.setattr("agents.dataCleaning_agent.sandbox_status", lambda: {"selected": "fallback"})
    monkeypatch.setattr(experiments, "run_isolated_transform", runner([]))
    turns = []
    def respond(messages, tools, **kwargs):
        turns.append(messages)
        def action(name, args):
            return {"content": None, "tool_calls": [{"id": str(len(turns)), "name": name, "arguments": args}]}
        if len(turns) == 1:
            assert "normalize_values" not in {t["function"]["name"] for t in tools}
            return action("test_method", proposal())
        if len(turns) == 2:
            assert any("Data/method error returned to you" in (m.get("content") or "") for m in messages if m["role"] == "user")
            return action("test_method", proposal("generated"))
        result = json.loads(next(m["content"] for m in reversed(messages) if m["role"] == "tool"))
        if len(turns) == 3:
            assert "review_candidate" in {t["function"]["name"] for t in tools}
            return action("review_candidate", {"candidate_id": result["candidate_id"], "decision": "accept",
                                                "assessment": "Separate trials parsed every value and preserved populated cells"})
        if len(turns) == 4:
            return action("apply_candidate", {"candidate_id": result["candidate_id"]})
        return action("finish", {"summary": "Rejected lossy coercion, tested a currency parser and validated full data"})
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", respond)
    result = DataCleaningAgent(data_root=tmp_path / "run", use_llm=True).run(report)
    assert result.validation.all_passed and len(turns) == 5
    assert result.metadata["method_candidates"] and result.metadata["decisions"]
    persisted = json.loads(Path(result.metadata["result_path"]).with_name("execution_trace.json").read_text())
    assert persisted["issues"]["type:Revenue"]["status"] == "resolved"
