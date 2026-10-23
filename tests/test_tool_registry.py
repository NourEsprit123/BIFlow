import json

import pandas as pd

import agents.dataCleaning_agent as data_cleaning_agent
from agents.dataCleaning_agent import DataCleaningAgent
import dataCleaningTools.tool_registry as tool_registry
from dataCleaningTools.models import DatasetStatus
from dataCleaningTools.tool_registry import AgentSessionState, ToolExecutor
from dataCleaningTools.versioning import DatasetVersionManager


def _executor(tmp_path, *, approve_all=False, approved_step_ids=None):
    source = tmp_path / "input.csv"
    pd.DataFrame({"name": [" Alice ", "Bob"], "score": ["1", "bad"]}).to_csv(
        source, index=False
    )
    manager = DatasetVersionManager(tmp_path / "versions")
    original = manager.register_original(source, dataset_id="test-dataset")
    working = manager.create_working_copy(original)
    state = AgentSessionState(
        manager=manager,
        dataset_id="test-dataset",
        current_ref=working,
        source_ref=original,
        approve_all=approve_all,
        approved_step_ids=set(approved_step_ids or []),
    )
    return state, ToolExecutor(state)


def test_tool_executor_cleans_and_inspects_current_version(tmp_path):
    state, executor = _executor(tmp_path)

    cleaned = json.loads(
        executor.execute("trim_whitespace", {"columns": ["name"]})
    )
    inspected = json.loads(executor.execute("inspect_column", {"column": "name"}))

    assert cleaned["success"]
    assert cleaned["version"] == "V2"
    assert state.current_ref.version == "V2"
    assert inspected["sample_values"] == ["Alice", "Bob"]


def test_tool_executor_blocks_drop_column_without_approval(tmp_path):
    state, executor = _executor(tmp_path)

    result = json.loads(
        executor.execute("drop_column", {"columns": ["score"], "step_id": "drop-1"})
    )

    assert result["success"] is False
    assert result["approval_required"] is True
    assert state.current_ref.version == "V1"
    assert state.pending_approvals


def test_tool_executor_accepts_explicitly_approved_step(tmp_path):
    state, executor = _executor(tmp_path, approved_step_ids={"drop-1"})

    result = json.loads(
        executor.execute("drop_column", {"columns": ["score"], "step_id": "drop-1"})
    )
    final_df = state.manager.load(state.current_ref)
    changes = state.manager.get_changelog(state.dataset_id)

    assert result["success"]
    assert state.current_ref.status == DatasetStatus.WORKING
    assert "score" not in final_df.columns
    assert changes.entries[-1].approval_obtained is True


def test_custom_check_uses_sandbox_without_mutating_dataset(tmp_path, monkeypatch):
    state, executor = _executor(tmp_path)
    calls = {}

    def run_check(code, series, timeout_sec):
        calls["code"] = code
        calls["values"] = series.tolist()
        calls["timeout_sec"] = timeout_sec
        return {
            "passed": True,
            "metric": 2,
            "details": "Both names are non-empty.",
            "error": None,
            "backend": "docker",
        }

    monkeypatch.setattr(tool_registry, "run_sandboxed_check", run_check)
    result = json.loads(
        executor.execute(
            "run_custom_check",
            {
                "column": "name",
                "description": "Check that names are non-empty.",
                "code": (
                    "def custom_check(series):\n"
                    "    return {'passed': True, 'metric': len(series), "
                    "'details': 'checked'}"
                ),
            },
        )
    )

    assert result["success"] is True
    assert result["check_passed"] is True
    assert result["sample_size"] == 2
    assert calls["values"] == [" Alice ", "Bob"]
    assert calls["timeout_sec"] == 8
    assert state.current_ref.version == "V1"


def test_custom_check_reports_unavailable_sandbox_as_not_executed(
    tmp_path, monkeypatch
):
    state, executor = _executor(tmp_path)
    monkeypatch.setattr(
        tool_registry,
        "run_sandboxed_check",
        lambda *args, **kwargs: {
            "passed": False,
            "metric": 0.0,
            "details": "Check not run.",
            "error": "No isolated sandbox backend is available.",
            "backend": "fallback",
        },
    )

    result = json.loads(
        executor.execute(
            "run_custom_check",
            {
                "column": "name",
                "description": "Check names.",
                "code": "def custom_check(series): return {}",
            },
        )
    )

    assert result["success"] is False
    assert result["check_passed"] is None
    assert "No isolated sandbox" in result["error"]
    assert state.current_ref.version == "V1"


def test_llm_cleaning_agent_can_request_a_generated_sandbox_check(
    tmp_path, monkeypatch
):
    source = tmp_path / "customers.csv"
    pd.DataFrame({"name": ["Alice", "Bob"]}).to_csv(source, index=False)
    report = {
        "schema_version": "2.1",
        "dataset_ref": {
            "file_path": str(source.resolve()),
            "file_name": source.name,
            "rows": 2,
            "columns": 1,
        },
        "agent_summary": "Inspect customer names.",
    }
    code = (
        "def custom_check(series):\n"
        "    return {'passed': bool(series.notna().all()), "
        "'metric': len(series), 'details': 'non-null names'}"
    )
    responses = iter(
        [
            {
                "content": "I will check that names are present.",
                "tool_calls": [
                    {
                        "id": "check-1",
                        "name": "run_custom_check",
                        "arguments": {
                            "column": "name",
                            "description": "Check names are non-null.",
                            "code": code,
                        },
                    }
                ],
            },
            {
                "content": None,
                "tool_calls": [
                    {
                        "id": "finish-1",
                        "name": "finish",
                        "arguments": {"summary": "Custom check completed."},
                    }
                ],
            },
        ]
    )
    monkeypatch.setattr(
        data_cleaning_agent, "chat_with_tools", lambda *args, **kwargs: next(responses)
    )
    sandbox_calls = []

    def run_check(generated_code, series, timeout_sec):
        sandbox_calls.append((generated_code, series.tolist(), timeout_sec))
        return {
            "passed": True,
            "metric": 2,
            "details": "Both names are present.",
            "error": None,
            "backend": "docker",
        }

    monkeypatch.setattr(tool_registry, "run_sandboxed_check", run_check)
    monkeypatch.setattr(
        data_cleaning_agent,
        "sandbox_status",
        lambda: {"selected": "docker"},
    )

    result = DataCleaningAgent(
        data_root=tmp_path / "versions",
        search_roots=[tmp_path],
        use_llm=True,
    ).run(report)
    custom_check_step = next(
        item for item in result.metadata["step_log"] if "tool" in item
    )

    assert result.metadata["mode"] == "llm"
    assert result.metadata["finish_summary"] == "Custom check completed."
    assert custom_check_step["tool"] == "run_custom_check"
    assert custom_check_step["result_preview"]
    assert sandbox_calls == [(code, ["Alice", "Bob"], 8)]
    assert result.final_dataset.version == "V1"
