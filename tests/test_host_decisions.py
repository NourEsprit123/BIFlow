"""Open items (dropped, blocked, needs review) are settled per column after the run, without model calls."""
import json

import pandas as pd
import pytest

from agents.dataCleaning_agent import DataCleaningAgent
from dataCleaningTools.decisions import open_decisions
from dataCleaningTools.run_summary import summarize


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr("agents.dataCleaning_agent.sandbox_status", lambda: {})


def finished_run(tmp_path, monkeypatch, values=("2024-01-05", None, "2024-02-11", None, "2024-03-01"), dtype="str", autonomous=False):
    """The model gives no usable action on the missing-value task, so it is dropped and left for the host."""
    source = tmp_path / "customers.csv"
    pd.DataFrame({"signup": list(values)}).to_csv(source, index=False)
    report = {"dataset_ref": {"file_path": str(source), "file_name": source.name, "rows": len(values), "columns": 1},
              "column_profiles": {"signup": {"dtype": dtype, "missing_count": sum(v is None for v in values)}}}
    def respond(messages, tools, **kwargs):
        task = json.loads(messages[-1]["content"])["cleaning_focus"]["task"]
        if not task:
            return {"content": None, "tool_calls": [{"id": "f", "name": "finish", "arguments": {"summary": "Done"}}]}
        return {"content": "No business rule for blank dates", "tool_calls": []}
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", respond)
    agent = DataCleaningAgent(data_root=tmp_path / "versions", use_llm=True, autonomous=autonomous)
    return agent, agent.run(report)


def no_model(*args, **kwargs):
    raise AssertionError("Settling decisions must not call the model")


def test_open_items_are_one_decision_per_column(tmp_path, monkeypatch):
    _, result = finished_run(tmp_path, monkeypatch)
    [item] = open_decisions(result)
    assert item["key"] == "signup" and item["missing"] == 2 and item["can_fill"]
    assert summarize(result)["needs_you"] == 1 and summarize(result)["needs_you_names"] == ["decide signup"]


def test_accepting_as_is_waives_the_column_and_passes_validation(tmp_path, monkeypatch):
    agent, result = finished_run(tmp_path, monkeypatch)
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", no_model)
    resolved = agent.resolve_decisions(result, {"signup": {"action": "accept", "note": "Blank dates are fine"}})
    assert resolved.validation.all_passed and resolved.final_dataset.version == result.final_dataset.version
    rule = next(r for r in resolved.validation.rules if r.rule_name == "accepted_by_host:signup")
    assert rule.passed and "Blank dates are fine" in rule.message
    assert not open_decisions(resolved) and resolved.metadata["waived"] == {"signup": "Blank dates are fine"}
    assert pd.read_csv(resolved.final_dataset.path)["signup"].isna().sum() == 2  # data unchanged


def test_filling_with_a_chosen_value_marks_the_cells(tmp_path, monkeypatch):
    agent, result = finished_run(tmp_path, monkeypatch)
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", no_model)
    resolved = agent.resolve_decisions(result, {"signup": {"action": "fill", "value": "2024-01-01"}})
    final = pd.read_csv(resolved.final_dataset.path)
    assert resolved.validation.all_passed and resolved.final_dataset.version != result.final_dataset.version
    assert final["signup"].tolist() == ["2024-01-05", "2024-01-01", "2024-02-11", "2024-01-01", "2024-03-01"]
    assert final["signup_imputed"].tolist() == [False, True, False, True, False]
    assert resolved.metadata["host_decisions"][-1]["applied"]


def test_a_fill_value_that_does_not_match_the_column_is_refused(tmp_path, monkeypatch):
    agent, result = finished_run(tmp_path, monkeypatch, values=(10.0, None, 12.0), dtype="float")
    resolved = agent.resolve_decisions(result, {"signup": {"action": "fill", "value": "not a number"}})
    assert not resolved.metadata["host_decisions"][-1]["applied"]
    assert len(open_decisions(resolved)) == 1 and resolved.validation.status.value == "partial"


def run_with_unresolved_notes(tmp_path, monkeypatch, notes):
    """Like finished_run, but the model's finish lists unresolved notes (as qwen does)."""
    source = tmp_path / "customers.csv"
    pd.DataFrame({"signup": ["2024-01-05", None, "2024-02-11"]}).to_csv(source, index=False)
    report = {"dataset_ref": {"file_path": str(source), "file_name": source.name, "rows": 3, "columns": 1},
              "column_profiles": {"signup": {"dtype": "str", "missing_count": 1}}}
    def respond(messages, tools, **kwargs):
        task = json.loads(messages[-1]["content"])["cleaning_focus"]["task"]
        if not task:
            return {"content": None, "tool_calls": [{"id": "f", "name": "finish",
                                                     "arguments": {"summary": "Done", "unresolved": notes}}]}
        return {"content": "No business rule for blank dates", "tool_calls": []}
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", respond)
    agent = DataCleaningAgent(data_root=tmp_path / "versions", use_llm=True)
    return agent, agent.run(report)


def test_accepting_a_column_settles_the_models_note_about_it(tmp_path, monkeypatch):
    agent, result = run_with_unresolved_notes(tmp_path, monkeypatch, ["signup"])
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", no_model)
    resolved = agent.resolve_decisions(result, {"signup": {"action": "accept"}})
    assert resolved.validation.status.value == "passed" and not resolved.validation.exceptions
    assert summarize(resolved)["accepted"] == ["signup"]


def test_a_note_about_something_else_still_keeps_the_run_partial(tmp_path, monkeypatch):
    agent, result = run_with_unresolved_notes(tmp_path, monkeypatch, ["signup", "region spelling varies"])
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", no_model)
    resolved = agent.resolve_decisions(result, {"signup": {"action": "accept"}})
    assert resolved.validation.status.value == "partial"
    assert resolved.validation.exceptions == ["region spelling varies"]


def numeric_run(tmp_path, monkeypatch, strategy="mean", autonomous=False):
    """A whole-number column with blanks; the profiling model chose an imputation strategy."""
    source = tmp_path / "costs.csv"
    pd.DataFrame({"cost": [10, None, 20, 31, None]}).to_csv(source, index=False)
    report = {"dataset_ref": {"file_path": str(source), "file_name": source.name, "rows": 5, "columns": 1},
              "column_profiles": {"cost": {"dtype": "float64", "missing_count": 2, "imputation_strategy": strategy,
                                           "agent_reasoning": "Monthly cost; the average is representative."}}}
    def respond(messages, tools, **kwargs):
        task = json.loads(messages[-1]["content"])["cleaning_focus"]["task"]
        if not task:
            return {"content": None, "tool_calls": [{"id": "f", "name": "finish", "arguments": {"summary": "Done"}}]}
        return {"content": "Not sure how to fill costs", "tool_calls": []}
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", respond)
    agent = DataCleaningAgent(data_root=tmp_path / "versions", use_llm=True, autonomous=autonomous)
    return agent, agent.run(report)


def test_fill_suggestions_lead_with_the_profiling_models_choice(tmp_path, monkeypatch):
    _, result = numeric_run(tmp_path, monkeypatch)
    [item] = open_decisions(result)
    first, *others = item["suggestions"]
    assert first == {"strategy": "fill_mean", "label": "Mean", "value": 20, "recommended": True,
                     "source": "profiling", "reason": "Monthly cost; the average is representative."}
    assert {(s["strategy"], s["value"]) for s in others} == {("fill_median", 20), ("fill_mode", 10)}


def test_applying_a_suggested_strategy_fills_and_marks_the_blanks(tmp_path, monkeypatch):
    agent, result = numeric_run(tmp_path, monkeypatch, strategy="median")
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", no_model)
    resolved = agent.resolve_decisions(result, {"cost": {"action": "fill", "strategy": "fill_median"}})
    final = pd.read_csv(resolved.final_dataset.path)
    assert resolved.validation.all_passed and final["cost"].tolist() == [10, 20, 20, 31, 20]
    assert final["cost_imputed"].tolist() == [False, True, False, False, True]


def test_without_a_profiling_choice_the_column_type_decides(tmp_path, monkeypatch):
    _, result = numeric_run(tmp_path, monkeypatch, strategy=None)
    [item] = open_decisions(result)
    assert item["suggestions"][0]["strategy"] == "fill_median" and item["suggestions"][0]["source"] == "rule"



def test_autonomous_mode_fills_blanks_with_the_recommendation_itself(tmp_path, monkeypatch):
    _, result = numeric_run(tmp_path, monkeypatch, strategy="median", autonomous=True)
    final = pd.read_csv(result.final_dataset.path)
    assert result.validation.all_passed and final["cost"].tolist() == [10, 20, 20, 31, 20]
    [decision] = result.metadata["host_decisions"]
    assert decision["by"] == "model" and decision["action"] == "fill" and decision["applied"]
    summary = summarize(result)
    assert summary["autonomous"] and "the model settled" in summary["stop"] and not open_decisions(result)


def test_autonomous_mode_fills_blank_text_with_the_most_frequent_value(tmp_path, monkeypatch):
    _, result = finished_run(tmp_path, monkeypatch, autonomous=True)
    assert result.validation.all_passed and not open_decisions(result)
    assert [(d["action"], d["by"], d["applied"]) for d in result.metadata["host_decisions"]] == [("fill", "model", True)]


def test_autonomous_mode_keeps_what_it_cannot_fill_and_says_so(tmp_path, monkeypatch):
    # A type task the model never acts on is dropped; with no blanks to fill, the model keeps the column as it is.
    source = tmp_path / "flags.csv"
    pd.DataFrame({"flag": ["Yes", "No", "Yes"]}).to_csv(source, index=False)
    report = {"dataset_ref": {"file_path": str(source), "file_name": source.name, "rows": 3, "columns": 1},
              "column_profiles": {"flag": {"dtype": "str", "etl_cast_to": "boolean"}}}
    def respond(messages, tools, **kwargs):
        if not json.loads(messages[-1]["content"])["cleaning_focus"]["task"]:
            return {"content": None, "tool_calls": [{"id": "f", "name": "finish", "arguments": {"summary": "Done"}}]}
        return {"content": "Unsure", "tool_calls": []}
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", respond)
    result = DataCleaningAgent(data_root=tmp_path / "versions", use_llm=True, autonomous=True).run(report)
    assert not open_decisions(result)
    [decision] = result.metadata["host_decisions"]
    assert (decision["action"], decision["by"], decision["applied"]) == ("accept", "model", True)
    assert result.metadata["waived"]["flag"].startswith("Kept as is by the model in autonomous mode")
    assert summarize(result)["accepted_by_model"] == ["flag"] and summarize(result)["accepted"] == []


def duplicate_run(tmp_path, monkeypatch, autonomous=False):
    """Two exact duplicate rows and one row sharing only its id; the model never acts on the duplicates task."""
    source = tmp_path / "orders.csv"
    pd.DataFrame({"order_id": [1, 2, 2, 3, 3, 4], "region": ["N", "S", "S", "E", "W", "N"],
                  "amount": [5, 7, 7, 9, 8, 6]}).iloc[[0, 1, 2, 3, 4, 5, 0]].to_csv(source, index=False)
    report = {"dataset_ref": {"file_path": str(source), "file_name": source.name, "rows": 7, "columns": 3},
              "column_profiles": {"order_id": {"dtype": "int64"}, "region": {"dtype": "str"}, "amount": {"dtype": "int64"}},
              "cross_column_issues": [{"issue_id": "duplicate_rows", "columns": [], "severity": "MEDIUM",
                                       "description": "exact duplicate rows"}]}
    def respond(messages, tools, **kwargs):
        if not json.loads(messages[-1]["content"])["cleaning_focus"]["task"]:
            return {"content": None, "tool_calls": [{"id": "f", "name": "finish", "arguments": {"summary": "Done"}}]}
        return {"content": "Still inspecting", "tool_calls": []}
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", respond)
    agent = DataCleaningAgent(data_root=tmp_path / "versions", use_llm=True, autonomous=autonomous)
    return agent, agent.run(report)


def test_a_left_over_duplicates_task_offers_removing_exact_duplicates(tmp_path, monkeypatch):
    agent, result = duplicate_run(tmp_path, monkeypatch)
    [item] = [i for i in open_decisions(result) if any(t["category"] == "duplicates" for t in i["tasks"])]
    assert item["can_remove_duplicates"] and item["duplicate_rows"] == 2
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", no_model)
    resolved = agent.resolve_decisions(result, {item["key"]: {"action": "remove_duplicates"}})
    final = pd.read_csv(resolved.final_dataset.path)
    # Only rows equal in every column go; the two order 3 rows differ and both stay.
    assert len(final) == 5 and not final.duplicated().any() and final["order_id"].tolist().count(3) == 2
    [decision] = resolved.metadata["host_decisions"]
    assert (decision["action"], decision["by"], decision["applied"], decision["rows"]) == ("remove_duplicates", "host", True, 2)


def test_autonomous_mode_removes_exact_duplicates_instead_of_keeping_them(tmp_path, monkeypatch):
    _, result = duplicate_run(tmp_path, monkeypatch, autonomous=True)
    final = pd.read_csv(result.final_dataset.path)
    assert len(final) == 5 and not final.duplicated().any()
    removal = [d for d in result.metadata["host_decisions"] if d["action"] == "remove_duplicates"]
    assert [(d["by"], d["applied"]) for d in removal] == [("model", True)]
    assert result.validation.all_passed and not open_decisions(result)
