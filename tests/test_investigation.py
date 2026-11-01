import json
from pathlib import Path

import pandas as pd
import pytest

from dataCleaningTools import workflow
from dataCleaningTools.cleaning_tasks import active, model_view
from tests.test_cleaning_tasks import focused, call
from tests.test_cleaning_experiments import session
from tests.test_simple_workflow import flat


def inspect(executor, view="values", **kwargs):
    return json.loads(executor.execute("inspect_data", {"reason": "Answer the active investigation", "view": view,
        "column": "region", **kwargs}))


def test_duplicate_inspection_reuses_evidence_and_ignores_reason_and_defaults(focused, monkeypatch):
    state, executor, _ = focused
    original = Path(state.current_ref.path).read_bytes()
    first = inspect(executor)
    def forbidden(*a):
        raise AssertionError("Duplicate inspection must not execute again")
    monkeypatch.setattr(workflow, "read_inspection", forbidden)
    repeated = inspect(executor, limit=50, offset=0, question="Different explanation", expected_evidence="Same data")
    assert repeated["cached"] and repeated["previous_event"] == first["event_id"]
    assert repeated["cached_result"]["value_overview"] == first["value_overview"]
    assert "investigation" not in repeated["cached_result"]
    assert repeated["consecutive_stalls"] == 1 and "different inspection" in repeated["next_action"]
    assert model_view(state, executor)["investigation_progress"]["consecutive_stalls"] == 1
    assert Path(state.current_ref.path).read_bytes() == original


def test_new_view_accepts_reason_and_resets_stalls(focused):
    state, executor, _ = focused
    task_id = active(state)["id"]
    inspect(executor)
    inspect(executor)  # Duplicate query stalls, regardless of explanation.
    result = inspect(executor, "patterns", reason="Check whether labels have whitespace padding")
    assert result["pattern_counts"]["has_leading_trailing_space"] == 1
    assert state.inspection_progress[f"V1:{task_id}"]["consecutive_stalls"] == 0
    assert call(executor, "complete_task", task_id=task_id, disposition="reviewed", reason="Retain observed labels")["success"]
    assert active(state)["columns"] == ["amount"]


def test_three_stalls_defer_advisory_without_claiming_success_or_stopping_other_tasks(focused):
    state, executor, _ = focused
    task_id = active(state)["id"]
    inspect(executor)
    for _ in range(3):
        result = inspect(executor)
    assert result["task_deferred"] == task_id
    assert state.cleaning_tasks[0]["status"] == "needs_review"
    assert not state.finished and state.current_ref.version == "V1"
    assert active(state)["columns"] == ["amount"]
    assert "inspection_progress" in json.loads((state.manager.root/state.dataset_id/"execution_trace.json").read_text())


def test_measured_task_stall_sets_review_flag_instead_of_bypassing_checks(focused):
    state, executor, _ = focused
    state.cleaning_tasks = [t for t in state.cleaning_tasks if t["columns"] != ["region"]]
    kwargs = {"column": "amount"}
    inspect(executor, **kwargs)
    for _ in range(3):
        result = inspect(executor, **kwargs)
    assert result["task_deferred"]
    assert "amount" in state.flagged
    assert active(state)["columns"] == ["flag"]


def test_changed_dataset_version_allows_fresh_inspection(focused):
    state, executor, _ = focused
    inspect(executor)
    # A real accepted edit creates V2, invalidating inspection signatures from V1.
    trial = call(executor, "test_builtin", columns=["region"], hypothesis="Remove observed whitespace", operation="trim_whitespace", parameters={})
    assert call(executor, "apply_candidate", candidate_id=trial["candidate_id"], assessment="Trim only padding")["success"]
    state.focused_cleaning = False  # Read the same column after the actual version change.
    result = inspect(executor)
    assert result["version"] == "V2" and not result.get("cached")


def test_nonfocused_repeated_inspection_stops_with_precise_reason(session):
    state, executor, _ = session
    for _ in range(3):
        result = inspect(executor, "column", column="amount")
    assert state.finished and state.stop_reason == "inspection_stalled"
    assert not result["success"]


def test_repeated_page_with_identical_results_is_not_progress(focused, monkeypatch):
    state, executor, _ = focused
    monkeypatch.setattr(workflow, "read_inspection", lambda *args: {"matched_rows": 0, "examples": []})
    inspect(executor, "filtered", filter="negative", limit=1)
    result = inspect(executor, "filtered", filter="negative", limit=2,
                     question="Are there prices under -100?", expected_evidence="Matching rows")
    assert not result["success"] and "identical evidence" in result["error"]


def test_numeric_views_answer_extreme_and_invalid_value_questions(tmp_path):
    from dataCleaningTools.versioning import DatasetVersionManager
    from dataCleaningTools.inspection import investigate_column
    path = tmp_path/"numeric.csv"
    pd.DataFrame({"price": [5, 6, 7, 8, 9, 100, "bad", None], "quantity": [1, 2, 3, 4, 5, 6, 7, 8]}).to_csv(path, index=False)
    manager = DatasetVersionManager(tmp_path/"versions")
    ref = manager.register_original(path, dataset_id="numeric")
    def view(name, **kwargs):
        return investigate_column(ref, {"column": "price", "view": name, **kwargs}, manager)
    distribution = view("distribution")
    assert distribution["min"] == 5 and distribution["max"] == 100
    assert distribution["negative_count"] == 0 and distribution["iqr_lower_bound"] < 5
    assert distribution["iqr_outlier_count"] == 1 and distribution["non_numeric_count"] == 1
    assert view("extremes", limit=1)["largest"][0]["value"] == "100"
    assert view("filtered", filter="negative")["matched_rows"] == 0
    assert view("filtered", filter="iqr_outliers")["matched_rows"] == 1
    assert view("filtered", filter="non_numeric")["examples"][0]["value"] == "bad"
    assert view("filtered", filter="missing")["matched_rows"] == 1
    assert view("filtered", filter="greater_than", threshold=8)["matched_rows"] == 2
    assert view("relationships", related_column="quantity")["numeric_pair_count"] == 6


def test_rejected_requests_count_before_inspection_execution(focused):
    state, executor, _ = focused
    task_id = active(state)["id"]
    requests = [{"view": "distribution", "column": "value"}, {"view": "values"}, {"view": "nonexistent"}]
    for count, args in enumerate(requests, 1):
        result = json.loads(executor.execute("inspect_data", {"reason": "Investigate", **args}))
        assert result["consecutive_stalls"] == count
        assert "region" in result["error"]
    assert result["task_deferred"] == task_id and active(state)["columns"] == ["amount"]
    assert state.current_ref.version == "V1" and not state.finished


def test_category_guide_uses_real_names_and_does_not_push_conversion(focused):
    from dataCleaningTools.cleaning_tasks import request_guide
    state, executor, _ = focused
    base = 'Use columns=["<column>"] for test_builtin conversion'
    guide = request_guide(state, base)
    assert "region" in guide and "<column>" not in guide
    assert "test_builtin conversion" not in guide
    assert "columns" not in model_view(state, executor)["value_interpretation"]
    state.cleaning_tasks = [t for t in state.cleaning_tasks if t["columns"] != ["region"]]
    assert 'columns=["amount"]' in request_guide(state, base)
    assert list(model_view(state, executor)["value_interpretation"]["columns"]) == ["amount"]


def test_example_coverage_is_explicitly_separate_from_missingness():
    from dataCleaningTools.inspection import value_inventory
    result = value_inventory(pd.Series(range(1000)), limit=10)
    assert result["displayed_non_null_coverage_pct"] == 1.0
    assert result["missing_pct"] == 0 and result["null_count"] == 0
    assert "NOT" in result["coverage_meaning"]



def test_different_filter_questions_are_useful_even_when_both_return_no_rows(focused):
    state, executor, _ = focused
    first = inspect(executor, "filtered", filter="negative")
    second = inspect(executor, "filtered", filter="positive")
    assert first["matched_rows"] == second["matched_rows"] == 0
    assert second["investigation"]["new_evidence"] and "error" not in second
    progress = next(iter(state.inspection_progress.values()))
    assert progress["inspections"] == 2 and progress["consecutive_stalls"] == 0


def test_inspection_reads_once_and_exact_repeat_uses_no_dataset_reads(focused, monkeypatch):
    state, executor, _ = focused
    original = state.manager.load
    reads = []
    def counted(ref):
        reads.append(ref.version)
        return original(ref)
    monkeypatch.setattr(state.manager, "load", counted)
    inspect(executor)
    assert reads == ["V1"]
    reads.clear()
    assert inspect(executor)["cached"]
    assert reads == []


def test_another_task_can_consume_cached_evidence_without_a_stall(focused, monkeypatch):
    state, executor, _ = focused
    first = inspect(executor)
    new_task = {"id": "task-99", "category": "domain", "columns": ["region"], "status": "pending", "evidence": []}
    state.cleaning_tasks.insert(0, new_task)
    def forbidden(*args):
        raise AssertionError("Existing version evidence must be reused")
    monkeypatch.setattr(workflow, "read_inspection", forbidden)
    reused = inspect(executor)
    assert reused["cached"] and reused["previous_event"] == first["event_id"]
    assert not reused["investigation"]["new_evidence"] and "error" not in reused
    assert state.inspection_progress["V1:task-99"]["consecutive_stalls"] == 0
    repeated = inspect(executor)
    assert repeated["consecutive_stalls"] == 1
    assert call(executor, "complete_task", task_id="task-99", disposition="reviewed", reason="Current labels inspected and retained")["success"]


@pytest.mark.parametrize("view,options", [
    ("schema", {"column": "region"}), ("patterns", {"limit": 2}),
    ("distribution", {"offset": 5}), ("filtered", {"filter": "negative", "threshold": 2}),
    ("filtered", {}), ("filtered", {"filter": "less_than"}),
    ("relationships", {"related_column": "region"}),
])
def test_unused_or_incomplete_view_options_do_not_reach_the_reader(focused, monkeypatch, view, options):
    state, executor, _ = focused
    def forbidden(*args):
        raise AssertionError("Invalid view options must not execute")
    monkeypatch.setattr(workflow, "read_inspection", forbidden)
    result = inspect(executor, view, **options)
    assert not result["success"] and result["consecutive_stalls"] == 1
    assert state.current_ref.version == "V1"


def test_values_past_the_end_do_not_gain_progress_from_offset_metadata(focused):
    state, executor, _ = focused
    inspect(executor, offset=100)
    result = inspect(executor, offset=101)
    assert result["error_kind"] == "inspection_no_progress" and "identical evidence" in result["error"]


def test_duplicate_keys_are_honored_counted_exactly_and_order_independent(flat):
    state, executor = flat
    frame = pd.DataFrame({"amount": [1, 1, 1, 2, 2, 3], "flag": ["A", "A", "B", "C", "D", "E"]})
    frame.to_csv(state.current_ref.path, index=False)
    full = call(executor, "inspect_data", reason="Find repeated records", view="duplicates")
    assert full["duplicate_row_count"] == 2 and full["duplicate_group_count"] == 1
    keys = call(executor, "inspect_data", reason="Inspect repeated amounts", view="duplicates", column="amount", limit=1)
    assert keys["subset"] == ["amount"] and keys["duplicate_row_count"] == 5
    assert keys["duplicate_group_count"] == 2 and keys["redundant_row_count"] == 3
    assert len(keys["sample_duplicate_rows"]) == 1
    repeated = call(executor, "inspect_data", reason="Same requested key", view="duplicates", subset=["amount"], limit=1)
    assert repeated["cached"]
    first = call(executor, "inspect_data", reason="Check compound key", view="duplicates", subset=["flag", "amount"])
    again = call(executor, "inspect_data", reason="Same compound key", view="duplicates", subset=["amount", "flag"])
    assert first["duplicate_group_count"] == 1 and again["cached"]


def test_duplicate_key_inspection_cannot_escape_the_active_task(focused):
    state, executor, _ = focused
    result = call(executor, "inspect_data", reason="Wrong task key", view="duplicates", subset=["amount"])
    assert not result["success"] and "current task" in result["error"]


def test_numeric_examples_preserve_positions_with_duplicate_index_labels(flat, monkeypatch):
    from dataCleaningTools.inspection import investigate_column
    state, _ = flat
    frame = pd.DataFrame({"amount": [5, -2, 10], "flag": [1, 2, 3]}, index=["same", "same", "other"])
    monkeypatch.setattr(state.manager, "load", lambda ref: frame)
    result = investigate_column(state.current_ref, {"column": "amount", "view": "filtered", "filter": "negative"}, state.manager)
    assert result["matched_rows"] == 1
    assert result["examples"] == [{"row_position": 1, "row_index": "same", "value": "-2"}]
    extreme = investigate_column(state.current_ref, {"column": "amount", "view": "extremes", "limit": 1}, state.manager)
    assert extreme["smallest"] == result["examples"]


def test_boolean_distribution_is_read_only_and_does_not_crash_quantiles(flat, monkeypatch):
    from dataCleaningTools.inspection import investigate_column
    state, _ = flat
    frame = pd.DataFrame({"flag": [True, False, True]})
    original = frame.copy(deep=True)
    monkeypatch.setattr(state.manager, "load", lambda ref: frame)
    result = investigate_column(state.current_ref, {"column": "flag", "view": "distribution"}, state.manager)
    assert result["min"] == 0 and result["max"] == 1 and result["positive_count"] == 2
    pd.testing.assert_frame_equal(frame, original)



def test_column_statistics_parse_numeric_values_once_and_exclude_infinity(flat, monkeypatch):
    from dataCleaningTools import inspection
    state, _ = flat
    frame = pd.DataFrame({"amount": ["2", "4", "bad", "inf", None]})
    monkeypatch.setattr(state.manager, "load", lambda ref: frame)
    original = inspection.pd.to_numeric
    calls = []
    def counted(values, **kwargs):
        calls.append(1)
        return original(values, **kwargs)
    monkeypatch.setattr(inspection.pd, "to_numeric", counted)
    result = inspection.inspect_column(state.current_ref, "amount", manager=state.manager)
    assert len(calls) == 1
    assert (result["min"], result["max"], result["mean"]) == (2, 4, 3)


def test_empty_inspections_have_finite_serializable_counts(flat, monkeypatch):
    from dataCleaningTools import inspection
    state, _ = flat
    monkeypatch.setattr(state.manager, "load", lambda ref: pd.DataFrame({"amount": pd.Series([], dtype="str")}))
    schema = inspection.inspect_schema(state.current_ref, state.manager)
    column = inspection.inspect_column(state.current_ref, "amount", manager=state.manager)
    patterns = inspection.check_value_patterns(state.current_ref, "amount", state.manager)
    assert schema["columns"][0]["null_pct"] == column["null_pct"] == 0
    assert column["min"] is None and patterns["empty"] and patterns["total_non_null"] == 0
    json.dumps([schema, column, patterns], allow_nan=False)


def test_case_variant_examples_are_bounded_while_counts_cover_the_column(flat, monkeypatch):
    from itertools import product
    from dataCleaningTools import inspection
    state, _ = flat
    labels = [f"group{i}{suffix}" for i in range(25) for suffix in ("a", "A")]
    labels += ["".join(chars) for chars in product(*[(c, c.upper()) for c in "abcd"])]
    monkeypatch.setattr(state.manager, "load", lambda ref: pd.DataFrame({"label": labels}))
    result = inspection.check_value_patterns(state.current_ref, "label", state.manager)
    assert result["total_non_null"] == 66 and result["case_variant_group_count"] == 26
    assert len(result["case_variants"]) == 20 and len(result["case_variants"]["abcd"]) == 10


def test_direct_json_inspection_uses_the_same_reader_as_managed_versions(flat, tmp_path):
    from dataCleaningTools.inspection import inspect_column
    state, _ = flat
    path = tmp_path / "values.json"
    pd.DataFrame({"amount": [1, 2]}).to_json(path, orient="records")
    ref = state.current_ref.model_copy(update={"path": str(path), "format": "json"})
    result = inspect_column(ref, "amount")
    assert result["min"] == 1 and result["max"] == 2
