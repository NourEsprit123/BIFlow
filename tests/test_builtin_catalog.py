"""Parameterized builtins: dates, missing markers, duplicates and outliers."""
import json

import pandas as pd
import pytest

from dataCleaningTools import cleaning, workflow
from dataCleaningTools.tool_registry import AgentSessionState, ToolExecutor
from dataCleaningTools.versioning import DatasetVersionManager


def executor_for(tmp_path, frame, **state_options):
    source = tmp_path / "input.csv"
    frame.to_csv(source, index=False)
    manager = DatasetVersionManager(tmp_path / "versions")
    original = manager.register_original(source, dataset_id="input")
    state = AgentSessionState(manager=manager, dataset_id="input", source_ref=original,
        current_ref=manager.create_working_copy(original), expected_columns=list(frame.columns), **state_options)
    return state, ToolExecutor(state)


def call(executor, name, **args):
    return json.loads(executor.execute(name, args))


def builtin(executor, operation, columns, parameters=None):
    return call(executor, "test_builtin", hypothesis=f"Apply {operation}", columns=columns,
                operation=operation, parameters=parameters or {})


def test_parse_datetime_tries_formats_in_order_and_keeps_markers_missing():
    frame = pd.DataFrame({"d": ["2024-01-31", "15/02/2024", "n/a", "not a date", None]})
    result = cleaning.parse_datetime(frame, "d", formats=["%Y-%m-%d", "%d/%m/%Y"])
    assert result.success
    assert result.df["d"].dt.strftime("%Y-%m-%d").tolist()[:2] == ["2024-01-31", "2024-02-15"]
    assert result.df["d"].iloc[2:].isna().all() and result.details["became_null"] == 1


def test_parse_datetime_refuses_values_that_two_formats_read_differently():
    frame = pd.DataFrame({"d": ["03/04/2024", "25/12/2024"]})
    result = cleaning.parse_datetime(frame, "d", formats=["%m/%d/%Y", "%d/%m/%Y"])
    assert not result.success and result.details["ambiguous_examples"] == ["03/04/2024"]
    assert cleaning.parse_datetime(frame, "d", formats=["%d/%m/%Y"]).df["d"].dt.month.tolist() == [4, 12]


def test_parse_datetime_infers_with_dayfirst_without_formats():
    result = cleaning.parse_datetime(pd.DataFrame({"d": ["03/04/2024", "2024-05-06"]}), "d", dayfirst=True)
    assert result.df["d"].dt.strftime("%Y-%m-%d").tolist() == ["2024-04-03", "2024-05-06"]


def test_standardize_missing_replaces_only_markers():
    frame = pd.DataFrame({"city": ["Paris", " N/A ", "unknown", "", "Rome"], "n": [1.0, 2.0, 3.0, 4.0, 5.0]})
    result = cleaning.standardize_missing(frame, ["city", "n"], markers=["Unknown"])
    assert result.df["city"].isna().tolist() == [False, True, True, True, False]
    assert result.df["n"].tolist() == frame["n"].tolist() and result.affected_rows == 3


def test_handle_outliers_caps_iqr_and_blanks_explicit_bounds():
    frame = pd.DataFrame({"x": [10, 11, 12, 13, 1000], "y": [1.0, -5.0, 2.0, 3.0, 4.0]})
    capped = cleaning.handle_outliers(frame, ["x"], action="cap", method="iqr")
    assert capped.df["x"].max() < 1000 and capped.df["x"].iloc[:4].tolist() == [10, 11, 12, 13]
    assert pd.api.types.is_integer_dtype(capped.df["x"])
    blanked = cleaning.handle_outliers(frame, ["y"], action="set_missing", method="bounds", lower=0)
    assert blanked.df["y"].isna().tolist() == [False, True, False, False, False]
    assert not cleaning.handle_outliers(pd.DataFrame({"s": ["a"]}), ["s"]).success


def test_exact_duplicates_apply_but_keyed_removal_needs_approval(tmp_path):
    frame = pd.DataFrame({"id": [1, 1, 2, 2], "v": ["a", "a", "b", "c"]})
    state, executor = executor_for(tmp_path, frame)
    exact = builtin(executor, "remove_duplicates", ["id", "v"])
    assert exact["success"]
    assert call(executor, "apply_candidate", candidate_id=exact["candidate_id"], assessment="Exact copies")["success"]
    assert state.current_ref.version == "V2" and state.current_ref.row_count == 3

    keyed = builtin(executor, "remove_duplicates", ["id"])
    applied = call(executor, "apply_candidate", candidate_id=keyed["candidate_id"], assessment="id is the key")
    assert keyed["success"] and applied["approval_required"] and state.current_ref.version == "V2"


def test_parse_datetime_registers_a_datetime_obligation(tmp_path):
    state, executor = executor_for(tmp_path, pd.DataFrame({"d": ["2024-01-31", "2024-02-01"]}))
    trial = builtin(executor, "parse_datetime", ["d"], {"formats": ["%Y-%m-%d"]})
    assert trial["success"] and call(executor, "apply_candidate", candidate_id=trial["candidate_id"], assessment="ISO dates")["success"]
    assert state.required_targets == {"d": "datetime"}


def test_bounds_method_requires_a_bound(tmp_path):
    _, executor = executor_for(tmp_path, pd.DataFrame({"x": [1.0, 2.0]}))
    result = builtin(executor, "handle_outliers", ["x"], {"action": "cap", "method": "bounds"})
    assert not result["success"] and "lower and/or upper" in result["error"]


@pytest.mark.parametrize("category, offered, refused", [
    ("types", "parse_datetime", "handle_outliers"),
    ("duplicates", "remove_duplicates", "convert_data_types"),
    ("outliers", "handle_outliers", "remove_duplicates"),
])
def test_each_category_sees_and_accepts_only_its_operations(tmp_path, category, offered, refused):
    state, executor = executor_for(tmp_path, pd.DataFrame({"x": [1.0, 2.0]}))
    state.focused_cleaning = True
    state.cleaning_tasks = [{"id": "task-1", "category": category, "columns": ["x"], "evidence": [], "status": "pending"}]
    schema = next(t for t in workflow.available_tools(state) if t["function"]["name"] == "test_builtin")
    enum = schema["function"]["parameters"]["properties"]["operation"]["enum"]
    assert offered in enum and refused not in enum
    result = builtin(executor, refused, ["x"])
    assert not result["success"]
    assert any(text in result.get("original_error", result["error"]) for text in ("not available", "only in"))
