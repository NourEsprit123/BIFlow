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
    result = cleaning.parse_datetime(frame, "d", date_formats=["%Y-%m-%d", "%d/%m/%Y"])
    assert result.success
    assert result.df["d"].dt.strftime("%Y-%m-%d").tolist()[:2] == ["2024-01-31", "2024-02-15"]
    assert result.df["d"].iloc[2:].isna().all() and result.details["became_null"] == 1


def test_parse_datetime_refuses_values_that_two_formats_read_differently():
    frame = pd.DataFrame({"d": ["03/04/2024", "25/12/2024"]})
    result = cleaning.parse_datetime(frame, "d", date_formats=["%m/%d/%Y", "%d/%m/%Y"])
    assert not result.success and result.details["ambiguous_examples"] == ["03/04/2024"]
    assert cleaning.parse_datetime(frame, "d", date_formats=["%d/%m/%Y"]).df["d"].dt.month.tolist() == [4, 12]


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
    trial = builtin(executor, "parse_datetime", ["d"], {"date_formats": ["%Y-%m-%d"]})
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


def outlier_task(tmp_path, frame, **state_options):
    tmp_path.mkdir(parents=True, exist_ok=True)
    state, executor = executor_for(tmp_path, frame, **state_options)
    state.focused_cleaning = True
    state.cleaning_tasks = [{"id": "task-1", "category": "outliers", "columns": ["x"], "evidence": [], "status": "pending"}]
    return state, executor


def cap(executor):
    trial = builtin(executor, "handle_outliers", ["x"], {"action": "cap", "method": "iqr"})
    return trial, call(executor, "apply_candidate", candidate_id=trial["candidate_id"], assessment="Cap the extreme value")


def test_outlier_value_changes_wait_for_host_approval_and_close_the_task(tmp_path):
    frame = pd.DataFrame({"x": [10.0, 11.0, 12.0, 13.0, 1000.0]})
    state, executor = outlier_task(tmp_path / "first", frame)
    trial, applied = cap(executor)
    assert trial["success"] and applied["approval_required"] and state.current_ref.version == "V1"
    assert applied["impact"]["rows_changed"] == 1 and "would change 1 of 5 rows" in state.pending_approvals[0]
    # The task waits for the host without freezing its columns.
    assert state.cleaning_tasks[0]["status"] == "awaiting_approval" and not state.flagged

    # A later run started with that approval commits the same builtin change.
    state, executor = outlier_task(tmp_path / "approved", frame, approved_step_ids={applied["step_id"]})
    _, approved = cap(executor)
    assert approved["success"] and state.current_ref.version == "V2" and not state.pending_approvals


def test_dtype_only_outlier_change_needs_no_approval(tmp_path):
    state, executor = outlier_task(tmp_path, pd.DataFrame({"x": [10, 11, 12, 13, 14]}))
    trial, applied = cap(executor)  # nothing is outside the bounds
    assert applied["success"] and applied["no_op"] and not state.pending_approvals
    assert state.current_ref.version == "V1"


def test_generated_method_without_checks_keeps_column_types(tmp_path, monkeypatch):
    seen = []
    def experiment(state, arguments):
        seen.append(arguments["checks"])
        return {"success": False, "tested": False, "candidate_id": "x1", "error": "not run in this test"}
    monkeypatch.setattr(workflow, "experiment", experiment)
    state, executor = outlier_task(tmp_path, pd.DataFrame({"x": [1.5, 2.5]}))
    state.sandbox_checked = True  # no Docker probe in this unit test
    result = call(executor, "test_generated", hypothesis="No checks given", columns=["x"],
                  code="def transform(df):\n    return df")
    assert result.get("error_kind") != "invalid_tool_arguments"
    assert {"column": "x", "kind": "numeric"} in seen[0] and {"column": "x", "kind": "preserve_missing"} in seen[0]


@pytest.mark.parametrize("target, offered, hidden", [
    ("float64", "clean_numeric_string", "parse_datetime"),
    ("datetime", "parse_datetime", "clean_numeric_string"),
    ("boolean", "convert_data_types", "parse_datetime"),
])
def test_type_tasks_see_only_parsers_for_their_target(tmp_path, target, offered, hidden):
    state, executor = executor_for(tmp_path, pd.DataFrame({"x": ["1", "2"]}), required_targets={"x": target})
    state.focused_cleaning = True
    state.cleaning_tasks = [{"id": "task-1", "category": "types", "columns": ["x"], "evidence": [],
                             "measured": "type_conversion", "status": "pending"}]
    schema = next(t for t in workflow.available_tools(state) if t["function"]["name"] == "test_builtin")
    enum = schema["function"]["parameters"]["properties"]["operation"]["enum"]
    assert offered in enum and hidden not in enum
    refused = builtin(executor, hidden, ["x"])
    assert not refused["success"] and "not available" in refused.get("original_error", refused["error"])


def test_numeric_builtin_parses_what_the_independent_check_expects(tmp_path):
    frame = pd.DataFrame({"v": ["$1,200.50", "1.5k", "one thousand", "quarter million", "(500)", "banana", "n/a"]})
    state, executor = executor_for(tmp_path, frame, required_targets={"v": "float"})
    trial = builtin(executor, "clean_numeric_string", ["v"])
    assert trial["success"], trial.get("error")
    parsed = cleaning.clean_numeric_string(frame, "v").df["v"]
    assert parsed.iloc[:5].tolist() == [1200.5, 1500.0, 1000.0, 250000.0, -500.0] and parsed.iloc[5:].isna().all()


def test_empty_missing_marker_is_accepted(tmp_path):
    _, executor = executor_for(tmp_path, pd.DataFrame({"c": ["a", "", "b"]}))
    assert builtin(executor, "standardize_missing", ["c"], {"markers": [""]})["success"]


def test_fill_keeps_counts_whole_marks_imputed_cells_and_passes_validation(tmp_path, monkeypatch):
    from agents.dataCleaning_agent import DataCleaningAgent
    source = tmp_path / "orders.csv"
    pd.DataFrame({"qty": [3, None, 2, 1, None], "price": [1.5, 2.5, None, 3.5, 4.5]}).to_csv(source, index=False)
    report = {"dataset_ref": {"file_path": str(source), "file_name": source.name, "rows": 5, "columns": 2},
              "column_profiles": {"qty": {"dtype": "float", "missing_count": 2}, "price": {"dtype": "float", "missing_count": 1}}}
    def respond(messages, tools, **kwargs):
        task = json.loads(messages[-1]["content"])["cleaning_focus"]["task"]
        name, args = ("finish", {"summary": "Filled"}) if not task else ("test_builtin", {
            "hypothesis": "Median fill", "columns": task["columns"], "operation": "handle_missing_values",
            "parameters": {"strategy": "fill_median"}})
        return {"content": None, "tool_calls": [{"id": name, "name": name, "arguments": args}]}
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", respond)
    monkeypatch.setattr("agents.dataCleaning_agent.sandbox_status", lambda: {})
    result = DataCleaningAgent(data_root=tmp_path / "versions", use_llm=True).run(report)
    final = pd.read_csv(result.final_dataset.path)
    assert result.validation.all_passed, [r.message for r in result.validation.rules if not r.passed]
    assert list(final.columns) == ["qty", "price", "qty_imputed", "price_imputed"]
    assert final["qty"].tolist() == [3, 2, 2, 1, 2]  # median 2, still whole numbers
    assert final["qty_imputed"].tolist() == [False, True, False, False, True]
    assert final["price"].tolist()[2] == 3.0 and final["price_imputed"].tolist() == [False, False, True, False, False]


def test_only_markers_for_the_filled_columns_may_be_added():
    from dataCleaningTools.effects import assess_candidate
    before = pd.DataFrame({"a": [1.0, None]})
    after = before.fillna(1.0).assign(a_imputed=[False, True])
    assert assess_candidate(before, after, "handle_missing_values", ["a"], {"strategy": "fill_median"})["accepted"]
    sneaky = after.assign(extra=[1, 2])
    assert not assess_candidate(before, sneaky, "handle_missing_values", ["a"], {"strategy": "fill_median"})["accepted"]
    assert not assess_candidate(before, after, "trim_whitespace", ["a"], {})["accepted"]


def test_type_task_help_says_what_each_parser_does(tmp_path):
    state, _ = executor_for(tmp_path, pd.DataFrame({"x": ["$1"]}), required_targets={"x": "float"})
    state.focused_cleaning = True
    state.cleaning_tasks = [{"id": "task-1", "category": "types", "columns": ["x"], "evidence": [],
                             "measured": "type_conversion", "status": "pending"}]
    help_text = next(t for t in workflow.available_tools(state) if t["function"]["name"] == "test_builtin")["function"]["description"]
    assert "strips no symbols" in help_text and "number words" in help_text


def test_redundant_numeric_target_is_accepted_and_bad_settings_name_the_allowed_ones(tmp_path):
    frame = pd.DataFrame({"Revenue": ["$1,200.50", "1.5k", "one thousand", "banana"]})
    _, executor = executor_for(tmp_path, frame, required_targets={"Revenue": "float64"})
    ok = builtin(executor, "clean_numeric_string", ["Revenue"], {"errors": "coerce", "target_type": "float"})
    assert ok["success"], ok.get("error")
    bad = builtin(executor, "clean_numeric_string", ["Revenue"], {"errors": "coerce", "method": "iqr", "k": 1.5})
    assert not bad["success"] and "clean_numeric_string accepts only: errors" in bad["error"]


def test_request_correction_sees_only_the_task_operations(tmp_path):
    from dataCleaningTools.request_correction import correct_request
    state, executor = executor_for(tmp_path, pd.DataFrame({"Revenue": ["$1", "2k"]}), required_targets={"Revenue": "float"})
    state.focused_cleaning = True
    state.cleaning_tasks = [{"id": "task-1", "category": "types", "columns": ["Revenue"], "evidence": [],
                             "measured": "type_conversion", "status": "pending"}]
    offered = []
    def generate(messages, tools, **kwargs):
        offered.append(tools[0])
        return {"tool_calls": []}
    args = {"hypothesis": "Parse revenue", "columns": ["Revenue"], "operation": "clean_numeric_string",
            "parameters": {"errors": "coerce", "markers": ["banana"]}}
    first = call(executor, "test_builtin", **args)
    correct_request("test_builtin", args, first, executor=executor, generate=generate)
    properties = offered[0]["function"]["parameters"]["properties"]
    assert "handle_outliers" not in properties["operation"]["enum"]
    assert not {"method", "k", "lower", "upper"} & set(properties["parameters"]["properties"])
