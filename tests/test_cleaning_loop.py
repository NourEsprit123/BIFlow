import json
from pathlib import Path

import pandas as pd
import pytest

from agents.dataCleaning_agent import DataCleaningAgent
from dataCleaningTools.models import CleaningResult


@pytest.fixture(autouse=True)
def offline_sandbox(monkeypatch):
    monkeypatch.setattr("agents.dataCleaning_agent.sandbox_status", lambda: {"selected": "fallback"})


def action(name, **arguments):
    return {"content": None, "finish_reason": "tool_calls", "tool_calls": [
        {"id": name, "name": name, "arguments": arguments}]}


def telco_report():
    root = Path(__file__).resolve().parents[1]
    # Do not depend on a report overwritten by live profiling experiments.
    return {"dataset_ref": {"file_path": str(root / "data/raw/telco_churn.csv"),
                            "file_name": "telco_churn.csv", "rows": 7043, "columns": 21},
            "column_profiles": {
                "TotalCharges": {"dtype": "str", "missing_count": 11, "etl_cast_to": "numeric"},
                **{c: {"dtype": "str", "etl_cast_to": "boolean"} for c in
                   ["Partner", "Dependents", "PhoneService", "PaperlessBilling", "Churn"]}}}


def test_telco_continues_after_narrative_at_turn_four_and_cleans_remaining_columns(tmp_path, monkeypatch):
    responses = [action("inspect_schema"), action("inspect_column", column="TotalCharges"),
                 action("trim_whitespace", columns=["TotalCharges"], rationale="Trim numeric text"),
                 {"content": "Whitespace removed. Next I should fill missing values and convert flags.", "tool_calls": []},
                 action("convert_data_types", column="TotalCharges", target_type="numeric"),
                 action("handle_missing_values", columns=["TotalCharges"], strategy="fill_median")]
    responses.extend(action("convert_data_types", column=c, target_type="boolean") for c in
                     ["Partner", "Dependents", "PhoneService", "PaperlessBilling", "Churn"])
    responses.append(action("finish", summary="Charges and flags prepared"))
    iterator = iter(responses)
    feedback_sizes = []
    def respond(messages, *args, **kwargs):
        feedback_sizes.extend(len(m["content"]) for m in messages if m["role"] == "tool" and '"effect"' in m["content"])
        return next(iterator)
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", respond)
    result = DataCleaningAgent(data_root=tmp_path, use_llm=True).run(telco_report())
    assert result.validation.all_passed
    assert result.metadata["stop_reason"] == "completed"
    df = pd.read_csv(result.final_dataset.path)
    assert len(df) == 7043 and not df.TotalCharges.isna().any()
    assert pd.api.types.is_bool_dtype(df.Partner)
    assert max(feedback_sizes) < 4000
    persisted = CleaningResult.model_validate_json(Path(result.metadata["result_path"]).read_text(encoding="utf-8"))
    assert persisted.validation.all_passed and persisted.metadata["events"] == result.metadata["events"]


def test_provider_error_after_trim_is_persisted_with_exact_turn(tmp_path, monkeypatch):
    class ProviderFailure(RuntimeError):
        status_code = 429
    count = 0
    def respond(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 1:
            return action("trim_whitespace", columns=["TotalCharges"])
        raise ProviderFailure("Synthetic token limit error")
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", respond)
    result = DataCleaningAgent(data_root=tmp_path, use_llm=True).run(telco_report())
    assert not result.validation.all_passed
    assert result.metadata["stop_reason"] == "provider_error"
    assert result.metadata["provider_errors"][0]["turn"] == 2
    assert result.metadata["provider_errors"][0]["status_code"] == 429
    trace = json.loads((Path(result.final_dataset.path).parent / "execution_trace.json").read_text(encoding="utf-8"))
    assert trace["provider_errors"][0]["message"] == "Synthetic token limit error"
    assert trace["events"][0]["tool"] == "trim_whitespace"
    assert Path(result.metadata["result_path"]).is_file()


def test_premature_finish_gets_validation_feedback_and_can_recover(tmp_path, monkeypatch):
    source = tmp_path / "input.csv"
    pd.DataFrame({"flag": ["Yes", "No"]}).to_csv(source, index=False)
    report = {"dataset_ref": {"file_path": str(source), "file_name": source.name, "rows": 2, "columns": 1},
              "column_profiles": {"flag": {"dtype": "str", "etl_cast_to": "boolean"}}}
    responses = iter([action("finish", summary="Done"),
                      action("convert_data_types", column="flag", target_type="boolean"),
                      action("finish", summary="Flags converted")])
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", lambda *a, **k: next(responses))
    result = DataCleaningAgent(data_root=tmp_path / "runs", use_llm=True).run(report)
    assert result.validation.all_passed
    assert result.metadata["stop_reason"] == "completed"


def test_three_consecutive_empty_responses_stop_with_explicit_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", lambda *a, **k: {"tool_calls": [], "content": "Thinking"})
    result = DataCleaningAgent(data_root=tmp_path, use_llm=True).run(telco_report())
    assert result.metadata["stop_reason"] == "no_tool_calls"
    assert not result.validation.all_passed
    assert len([s for s in result.metadata["step_log"] if "response_finish_reason" in s]) == 3


def test_run_budget_prevents_applying_a_late_model_response(tmp_path, monkeypatch):
    now = [100.0]
    monkeypatch.setattr("agents.dataCleaning_agent.time.monotonic", lambda: now[0])
    def respond(*args, **kwargs):
        assert kwargs["timeout"] == 5
        now[0] = 106.0
        return action("trim_whitespace", columns=["TotalCharges"])
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", respond)
    result = DataCleaningAgent(data_root=tmp_path, use_llm=True, max_seconds=5).run(telco_report())
    assert result.metadata["stop_reason"] == "time_budget"
    assert not result.change_log.entries
    assert result.final_dataset.version == "V1"


def test_repeated_inspection_on_unchanged_data_stops_as_stalled(tmp_path, monkeypatch):
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", lambda *a, **k: action("inspect_schema"))
    result = DataCleaningAgent(data_root=tmp_path, use_llm=True).run(telco_report())
    assert result.metadata["stop_reason"] == "stalled"
    assert result.metadata["turns_used"] == 3
    assert not result.change_log.entries


def test_independent_tools_can_be_batched_in_a_single_model_turn(tmp_path, monkeypatch):
    source = tmp_path / "flags.csv"
    pd.DataFrame({"a": ["Yes", "No"], "b": ["No", "Yes"]}).to_csv(source, index=False)
    report = {"dataset_ref": {"file_path": str(source), "file_name": source.name, "rows": 2, "columns": 2},
              "column_profiles": {c: {"dtype": "str", "etl_cast_to": "boolean"} for c in ["a", "b"]}}
    batch = {"content": None, "tool_calls": [action("convert_data_types", column=c, target_type="boolean")["tool_calls"][0]
                                             for c in ["a", "b"]]}
    for index, call in enumerate(batch["tool_calls"]):
        call["id"] = f"convert-{index}"
    responses = iter([batch, action("finish", summary="Both flags converted")])
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", lambda *a, **k: next(responses))
    result = DataCleaningAgent(data_root=tmp_path / "runs", use_llm=True).run(report)
    assert result.validation.all_passed and result.metadata["turns_used"] == 2
    assert len(result.change_log.successful_ops()) == 2




def test_saved_run_recovers_after_session_loss_but_not_after_data_or_profile_changes(tmp_path, monkeypatch):
    import dashboard.workspace as workspace
    source = tmp_path / "sample.csv"
    source.write_text("value\n1\n2\n", encoding="utf-8")
    report = {"dataset_ref": {"file_path": str(source), "file_name": source.name, "rows": 2, "columns": 1}}
    original = DataCleaningAgent(data_root=tmp_path / "data/versions/dashboard", use_llm=False).run(report)
    monkeypatch.setattr(workspace, "ROOT", tmp_path)
    monkeypatch.setattr(workspace.st, "session_state", {})
    recovered = workspace.get_workspace_result(workspace.CLEANING_STATE_KEY, source)
    assert recovered.run_id == original.run_id
    workspace.st.session_state.clear()
    workspace.st.session_state[workspace.PROFILE_STATE_KEY] = {
        "signature": workspace.dataset_signature(source),
        "result": {"profiling_report": {**report, "agent_summary": "New interpretation"}},
    }
    assert workspace.get_workspace_result(workspace.CLEANING_STATE_KEY, source) is None
    workspace.st.session_state.clear()
    source.write_text("value\n100\n200\n", encoding="utf-8")
    assert workspace.get_workspace_result(workspace.CLEANING_STATE_KEY, source) is None




@pytest.mark.parametrize("code,expected_calls", [("tool_use_failed", 2), ("invalid_request_error", 1)])
def test_format_retries_are_bounded_and_other_bad_requests_abort(tmp_path, monkeypatch, code, expected_calls):
    class BadRequest(RuntimeError):
        status_code = 400
        body = {"code": code, "failed_generation": '{"name":"delete_file","arguments":{}}'}
    calls = []
    def respond(*a, **k):
        calls.append(1)
        raise BadRequest("Synthetic bad request")
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", respond)
    result = DataCleaningAgent(data_root=tmp_path, use_llm=True).run(telco_report())
    assert len(calls) == expected_calls
    assert result.metadata["stop_reason"] == "provider_error"
    assert [e["tool"] for e in result.metadata["events"]] == ["validate_dataset"]
    assert not result.change_log.entries
