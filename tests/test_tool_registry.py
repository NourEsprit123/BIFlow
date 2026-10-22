import json

import pandas as pd

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
