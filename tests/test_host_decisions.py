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


def finished_run(tmp_path, monkeypatch, values=("2024-01-05", None, "2024-02-11", None, "2024-03-01"), dtype="str"):
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
    agent = DataCleaningAgent(data_root=tmp_path / "versions", use_llm=True)
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
