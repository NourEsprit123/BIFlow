"""A failing task is dropped and reported; the run continues with the next independent task."""
import json

import pandas as pd
import pytest

from agents.dataCleaning_agent import DataCleaningAgent
from dataCleaningTools import cleaning_tasks
from tests.test_cleaning_loop import action


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr("agents.dataCleaning_agent.sandbox_status", lambda: {})


def report(tmp_path):
    """Two independent columns: flag (type task) and city (formatting, then missing on the same column)."""
    source = tmp_path / "input.csv"
    pd.DataFrame({"flag": ["Yes", "No", "Yes"], "city": ["Paris ", None, "Rome"]}).to_csv(source, index=False)
    return {"dataset_ref": {"file_path": str(source), "file_name": source.name, "rows": 3, "columns": 2},
            "column_profiles": {"flag": {"dtype": "str", "etl_cast_to": "boolean"},
                                "city": {"dtype": "str", "missing_count": 1,
                                         "issues": [{"issue_id": "whitespace", "description": "Trailing spaces"}]}}}


def run(tmp_path, monkeypatch, respond, **settings):
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", respond)
    return DataCleaningAgent(data_root=tmp_path / "versions", use_llm=True, **settings).run(report(tmp_path))


def focus(messages):
    return json.loads(messages[-1]["content"])["cleaning_focus"]["task"]


def failing_flag_trial(n):
    # Each target type is a distinct method that cannot represent Yes/No.
    return action("test_builtin", hypothesis=f"Attempt {n}", columns=["flag"], operation="convert_data_types",
                  parameters={"target_type": ["integer", "float", "numeric", "datetime"][n]})


def test_distinct_failed_attempts_drop_the_task_and_the_run_moves_on(tmp_path, monkeypatch):
    seen = []
    def respond(messages, tools, **kwargs):
        task = focus(messages)
        seen.append(task and task["columns"])
        if task and task["columns"] == ["flag"]:
            return failing_flag_trial(sum(c == ["flag"] for c in seen) - 1)
        return action("flag_for_review", columns=task["columns"], reason="Not part of this test") if task else \
            action("finish", summary="Flag could not be converted")
    result = run(tmp_path, monkeypatch, respond)
    drops = result.metadata["task_drops"]
    assert drops[0]["reason"] == "attempt_budget" and seen.count(["flag"]) == 4
    assert ["city"] in seen  # later, independent work still got turns
    assert result.validation.status.value == "partial" and "flag" in result.metadata["flagged"]
    assert any("attempt_budget" in issue for issue in result.unresolved_issues)


def test_turn_budget_drops_a_task_that_never_concludes(tmp_path, monkeypatch):
    monkeypatch.setenv("BIFLOW_CLEANING_TASK_MAX_TURNS", "2")
    def respond(messages, tools, **kwargs):
        task = focus(messages)
        if not task:
            return action("finish", summary="Done")
        if task["columns"] == ["flag"]:
            return {"content": "Still thinking", "tool_calls": []}
        return action("flag_for_review", columns=task["columns"], reason="Not part of this test")
    result = run(tmp_path, monkeypatch, respond)
    assert result.metadata["task_drops"][0]["reason"] == "turn_budget"
    assert result.metadata["stop_reason"] != "no_tool_calls"


def test_dropping_a_task_blocks_later_tasks_on_the_same_columns(tmp_path, monkeypatch):
    def respond(messages, tools, **kwargs):
        task = focus(messages)
        if not task:
            return action("finish", summary="Done")
        if task["category"] == "formatting":
            return {"content": "No idea", "tool_calls": []}
        return action("test_builtin", hypothesis="Yes/No flags", columns=["flag"],
                      operation="convert_data_types", parameters={"target_type": "boolean"})
    result = run(tmp_path, monkeypatch, respond)
    tasks = {t["category"]: t for t in result.metadata["cleaning_tasks"]}
    assert tasks["formatting"]["status"] == "dropped"
    assert tasks["missing"]["status"] == "blocked" and tasks["missing"]["blocked_by"] == tasks["formatting"]["id"]
    assert tasks["types"]["status"] == "done"
    # The blocked missing-value obligation is frozen for review: partial, not failed.
    assert result.validation.status.value == "partial" and "city" in result.metadata["flagged"]


def test_a_second_stop_in_one_pipeline_does_not_drop_the_next_task(tmp_path, monkeypatch):
    states = []
    def execute(self, executor, name, args):
        state = executor.state
        task = cleaning_tasks.active(state)
        executor.stop("tool_execution_error", "first failure")
        if not cleaning_tasks.closed(state, task):
            executor.stop("correction_exhausted", "must not reach the next task")
        states.append([t["status"] for t in state.cleaning_tasks])
        return {"success": False, "error": "failed"}
    monkeypatch.setattr(DataCleaningAgent, "_execute_action", execute)
    calls = []
    def respond(messages, tools, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return failing_flag_trial(0)
        return action("finish", summary="Done")
    run(tmp_path, monkeypatch, respond)
    assert states[0].count("dropped") == 1 and "pending" in states[0]


def test_stop_without_a_task_still_ends_the_run(tmp_path, monkeypatch):
    from dataCleaningTools.tool_registry import AgentSessionState, ToolExecutor
    from dataCleaningTools.versioning import DatasetVersionManager
    source = tmp_path / "x.csv"
    pd.DataFrame({"a": [1]}).to_csv(source, index=False)
    manager = DatasetVersionManager(tmp_path / "v")
    original = manager.register_original(source, dataset_id="x")
    state = AgentSessionState(manager=manager, dataset_id="x", source_ref=original,
                              current_ref=manager.create_working_copy(original))
    ToolExecutor(state).stop("correction_exhausted", "no queue")
    assert state.finished and state.stop_reason == "correction_exhausted"
