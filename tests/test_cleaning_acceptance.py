import json

import pandas as pd
import pytest

from agents.dataCleaning_agent import DataCleaningAgent
from dataCleaningTools.effects import assess_candidate
from dataCleaningTools.models import DatasetStatus, ValidationStatus
from dataCleaningTools.tool_registry import AgentSessionState, ToolExecutor
from dataCleaningTools.versioning import DatasetVersionManager


@pytest.fixture(autouse=True)
def no_container_probe(monkeypatch):
    monkeypatch.setattr("agents.dataCleaning_agent.sandbox_status", lambda: {"selected": "fallback"})


def session(tmp_path):
    source = tmp_path / "input.csv"
    pd.DataFrame({"name": [" Alice ", "Bob"], "score": ["1", "bad"]}).to_csv(source, index=False)
    manager = DatasetVersionManager(tmp_path / "versions")
    original = manager.register_original(source, dataset_id="test")
    state = AgentSessionState(manager=manager, dataset_id="test", source_ref=original,
                              current_ref=manager.create_working_copy(original))
    return state, ToolExecutor(state)


def test_lossy_conversion_is_rejected_without_changing_working_version(tmp_path):
    state, executor = session(tmp_path)
    original_bytes = open(state.source_ref.path, "rb").read()
    result = json.loads(executor.execute("convert_data_types", {"column": "score", "target_type": "numeric"}))
    assert not result["accepted"]
    assert state.current_ref.version == "V1"
    assert state.manager.load(state.current_ref)["score"].tolist() == ["1", "bad"]
    assert any(r["rule_name"] == "no_new_missing:score" and not r["passed"] for r in result["effect"]["rules"])
    record = state.manager.get_changelog("test").entries[-1]
    assert not record.success and record.source_version == record.result_version
    assert open(state.source_ref.path, "rb").read() == original_bytes
    assert not json.loads(executor.execute("finish", {"summary": "Done"}))["success"]


def test_inspection_evidence_and_effect_are_saved_with_action(tmp_path):
    state, executor = session(tmp_path)
    observation = json.loads(executor.execute("inspect_column", {"column": "name"}))
    result = json.loads(executor.execute("trim_whitespace", {
        "columns": ["name"], "rationale": "Inspection shows surrounding whitespace.",
        "evidence_ids": [observation["event_id"]],
    }))
    record = state.manager.get_changelog("test").entries[-1]
    assert result["accepted"] and result["effect"]["changed_cells"] == 1
    assert record.metadata["evidence_ids"] == [observation["event_id"]]
    assert record.rationale == "Inspection shows surrounding whitespace."
    assert state.events[-1]["evidence"][observation["event_id"]]["version"] == "V1"


def test_mutation_invalidates_previous_validation_and_finish_checks_new_version(tmp_path):
    state, executor = session(tmp_path)
    executor.execute("validate_dataset", {})
    assert state.validation.all_passed
    executor.execute("trim_whitespace", {"columns": ["name"]})
    assert state.validation is None
    executor.execute("finish", {"summary": "Trimmed names"})
    assert state.validation.all_passed and state.validation.dataset_ref.version == "V2"


def test_explicit_validation_targets_cannot_be_forgotten_at_finish(tmp_path):
    state, executor = session(tmp_path)
    assert not json.loads(executor.execute("validate_dataset", {"numeric_columns": ["score"]}))["success"]
    assert not json.loads(executor.execute("finish", {"summary": "Done"}))["success"]
    assert any(r.rule_name == "target_type:score" and not r.passed for r in state.validation.rules)


def test_ignored_conversion_cannot_claim_target_type_succeeded(tmp_path):
    state, executor = session(tmp_path)
    result = json.loads(executor.execute("convert_data_types", {
        "column": "score", "target_type": "numeric", "errors": "ignore",
    }))
    assert not result["accepted"] and state.current_ref.version == "V1"


def test_conversion_cannot_weaken_an_existing_validation_requirement(tmp_path):
    state, executor = session(tmp_path)
    state.required_targets["score"] = "numeric"
    executor.execute("convert_data_types", {"column": "score", "target_type": "string"})
    assert state.required_targets["score"] == "numeric"
    assert not json.loads(executor.execute("finish", {"summary": "Done"}))["success"]


def test_imputation_must_actually_resolve_missing_values(tmp_path):
    before = pd.DataFrame({"category": ["A", None]})
    result = assess_candidate(before, before.copy(), "handle_missing_values", ["category"], {"strategy": "fill_median"})
    assert not result["accepted"]
    assert any(r["rule_name"] == "missing_resolved:category" and not r["passed"] for r in result["rules"])


def test_finish_without_llm_validation_enforces_report_requirements(tmp_path, monkeypatch):
    source = tmp_path / "telco.csv"
    pd.DataFrame({"customerID": ["a", "b", "c"], "TotalCharges": ["10", " ", "20"]}).to_csv(source, index=False)
    report = {"dataset_ref": {"file_path": str(source), "file_name": source.name, "rows": 3, "columns": 2},
              "column_profiles": {"TotalCharges": {"dtype": "str", "missing_count": 1, "etl_cast_to": "numeric"}}}
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", lambda *a, **k: {
        "content": None, "tool_calls": [{"id": "done", "name": "finish", "arguments": {"summary": "Done"}}],
    })
    result = DataCleaningAgent(data_root=tmp_path / "runs", use_llm=True).run(report)
    assert result.validation.status == ValidationStatus.FAILED
    assert result.final_dataset.status == DatasetStatus.FAILED
    assert any(r.rule_name == "missing_resolved:TotalCharges" and not r.passed for r in result.validation.rules)


def test_separate_runs_preserve_originals_and_do_not_mix_changelogs(tmp_path):
    source = tmp_path / "input.csv"
    source.write_text("value\n1\n2\n", encoding="utf-8")
    report = {"dataset_ref": {"file_path": str(source), "file_name": source.name, "rows": 2, "columns": 1}}
    agent = DataCleaningAgent(data_root=tmp_path / "runs", use_llm=False)
    first = agent.run(report)
    source.write_text("value\n3\n4\n", encoding="utf-8")
    second = agent.run(report)
    assert first.source_dataset.path != second.source_dataset.path
    assert pd.read_csv(first.source_dataset.path)["value"].tolist() == [1, 2]
    assert not first.change_log.entries and not second.change_log.entries
    assert first.validation.all_passed and second.validation.all_passed


def test_unresolved_run_returns_failed_result_instead_of_crashing(tmp_path):
    source = tmp_path / "input.csv"
    pd.DataFrame({"value": [1, None]}).to_csv(source, index=False)
    report = {"dataset_ref": {"file_path": str(source), "file_name": source.name, "rows": 2, "columns": 1},
              "column_profiles": {"value": {"dtype": "float64", "missing_count": 1, "drop_recommended": True,
                                            "imputation_strategy": "median"}}}
    result = DataCleaningAgent(data_root=tmp_path / "runs", use_llm=False).run(report)
    assert result.validation.status == ValidationStatus.FAILED
    assert result.unresolved_issues
    assert "value" in pd.read_csv(result.final_dataset.path)


def test_successful_cleaning_checks_telco_column_and_emits_live_events(tmp_path, monkeypatch):
    source = tmp_path / "telco.csv"
    pd.DataFrame({"customerID": ["a", "b", "c"], "TotalCharges": ["10", " ", "20"]}).to_csv(source, index=False)
    report = {"dataset_ref": {"file_path": str(source), "file_name": source.name, "rows": 3, "columns": 2},
              "column_profiles": {"TotalCharges": {"dtype": "str", "missing_count": 1, "etl_cast_to": "numeric",
                  "issues": [{"issue_id": "missing_values", "description": "One blank value", "source": "python", "severity": "MEDIUM"}]}}}
    actions = iter([
        ("convert_data_types", {"column": "TotalCharges", "target_type": "numeric", "rationale": "Numeric text with one blank"}),
        ("handle_missing_values", {"columns": ["TotalCharges"], "strategy": "fill_median", "rationale": "Fill the reported blank for this test"}),
        ("finish", {"summary": "Converted charges and filled the missing value"}),
    ])
    def respond(*a, **k):
        name, arguments = next(actions)
        return {"content": None, "tool_calls": [{"id": name, "name": name, "arguments": arguments}]}
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", respond)
    events = []
    result = DataCleaningAgent(data_root=tmp_path / "runs", use_llm=True).run(report, on_event=events.append)
    assert result.validation.all_passed
    assert result.final_dataset.status == DatasetStatus.VALIDATED
    assert pd.read_csv(result.final_dataset.path)["TotalCharges"].tolist() == [10, 15, 20]
    assert any(r.rule_name == "target_type:TotalCharges" for r in result.validation.rules)
    assert len(result.change_log.successful_ops()) == 2
    assert result.change_log.entries[0].metadata["evidence_ids"] == ["profile:TotalCharges:missing_values:0"]
    assert [e["tool"] for e in events if "tool" in e] == [e["tool"] for e in result.metadata["events"]]


@pytest.mark.parametrize("live", [False, True])
def test_review_ui_shows_rejection_evidence_and_final_failed_checks(tmp_path, live):
    import socket
    from streamlit.testing.v1 import AppTest
    from dataCleaningTools.models import CleaningResult

    # AppTest creates an asyncio loop before its own timeout starts. Windows
    # restricted environments can block forever in that loop's socketpair.
    previous_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(2)
        pair = socket.socketpair()
        for connection in pair:
            connection.close()
    except (OSError, TimeoutError):
        pytest.skip("Streamlit AppTest requires local socketpair support")
    finally:
        socket.setdefaulttimeout(previous_timeout)

    state, executor = session(tmp_path)
    executor.execute("convert_data_types", {"column": "score", "target_type": "numeric"})
    executor.execute("finish", {"summary": "Conversion rejected; original values retained"})
    result = CleaningResult(source_dataset=state.source_ref, final_dataset=state.current_ref,
                            change_log=state.manager.get_changelog("test"), validation=state.validation,
                            metadata={"events": state.events, "evidence": state.evidence, "mode": "llm"})
    script = (
        "from dataCleaningTools.models import CleaningResult\n"
        "from dashboard.cleaning_review import render_cleaning_result\n"
        f"result = CleaningResult.model_validate_json({result.model_dump_json()!r})\n"
    )
    if live:
        script += (
            "from unittest.mock import patch\n"
            "from pathlib import Path\n"
            "import streamlit as st\n"
            "from dashboard.cleaning_review import run_cleaning_with_progress\n"
            "def run(path, on_event):\n"
            "    on_event({'phase': 'choosing next action'})\n"
            "    for event in result.metadata['events']:\n"
            "        on_event(event)\n"
            "    return result\n"
            "with patch('dashboard.workspace.clean_profiled_dataset', side_effect=run):\n"
            "    with st.status('Workflow', expanded=True):\n"
            "        run_cleaning_with_progress(Path('input.csv'))\n"
        )
    app = AppTest.from_string(script + "render_cleaning_result(result)\n").run(timeout=15)
    assert not app.exception
    assert any("Final validation: failed" in w.value for w in app.warning)
    assert any("Candidate rejected" in w.value for w in app.warning)
    assert any("Rejected" in exp.label for exp in app.expander)
    assert any("Supporting evidence" in item.value for item in app.markdown)
    assert len(app.dataframe) >= 3
