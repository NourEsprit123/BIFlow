import json
from pathlib import Path

import pandas as pd
import pytest

from dataCleaningTools.inspection import value_inventory
from tests.test_cleaning_experiments import session


def test_all_small_column_values_are_visible_including_late_formats():
    values = [str(n) for n in range(25)] + ["quarter million", "banana", None]
    overview = value_inventory(pd.Series(values))
    assert overview["scanned_rows"] == 28 and overview["null_count"] == 1
    assert overview["all_distinct_values_displayed"]
    assert overview["displayed_non_null_coverage_pct"] == 100
    assert {"quarter million", "banana"}.issubset({v["value"] for v in overview["values"]})
    assert sum(g["row_count"] for g in overview["format_groups"]) == 27


def test_pagination_exposes_every_distinct_value_without_duplicates():
    series = pd.Series(["frequent"] * 500 + [f"id-{i}" for i in range(130)])
    offset = 0
    observed = []
    while True:
        page = value_inventory(series, offset, 50)
        observed.extend(page["values"])
        assert page["scanned_rows"] == 630
        if page["next_offset"] is None:
            break
        offset = page["next_offset"]
    assert len(observed) == 131 and len({v["value"] for v in observed}) == 131
    assert sum(v["count"] for v in observed) == 630
    assert not value_inventory(series)["all_distinct_values_displayed"]


def test_rare_formats_are_visible_even_when_frequent_values_dominate():
    series = pd.Series(["1200.50"] * 1000 + ["five hundred", "ERROR_404", " 1.5k "])
    overview = value_inventory(series, limit=1)
    assert not overview["all_distinct_values_displayed"]
    examples = {e["value"] for g in overview["format_groups"] for e in g["examples"]}
    assert {"five hundred", "ERROR_404", " 1.5k "}.issubset(examples)
    assert overview["displayed_value_rows"] == 1000
    assert overview["displayed_format_rows"] == 1003


def test_empty_and_all_null_columns_have_explicit_coverage():
    for values in ([], [None, None]):
        overview = value_inventory(pd.Series(values, dtype="object"))
        assert overview["values"] == [] and overview["format_groups"] == []
        assert overview["next_offset"] is None and overview["all_distinct_values_displayed"]


def test_value_inspection_and_assessment_are_audited_without_changes(session):
    state, executor, _ = session
    original = Path(state.current_ref.path).read_bytes()
    page = json.loads(executor.execute("inspect_data", {"reason": "Review the unseen currency values", "view": "values",
        "column": "amount", "offset": 1, "limit": 1,
        "question": "What format is on the next page?", "expected_evidence": "A previously unseen raw value"}))
    assert page["version"] == "V1" and len(page["value_overview"]["values"]) == 1
    assert page["value_overview"]["next_offset"] == 2
    assessment = {"evidence": "V1, full column counts and paginated distinct amounts", "interpretation": "Dollar-prefixed numeric amounts",
        "preservation": "Strip only surrounding whitespace", "ambiguities": "Missing value still requires a justified policy"}
    result = json.loads(executor.execute(('test_builtin'), {"hypothesis": "Test whitespace hygiene", "columns": ["amount"],
        "operation": "trim_whitespace", "parameters": {}, "value_assessment": assessment}))
    assert result["success"]
    assert state.events[-1]["arguments"]["value_assessment"] == assessment
    assert state.method_candidates[result["candidate_id"]]["value_assessment"] == assessment
    assert Path(state.current_ref.path).read_bytes() == original


def test_value_page_bounds_are_validated(session):
    _, executor, _ = session
    for options in ({"offset": -1}, {"limit": 0}, {"limit": 101}):
        result = json.loads(executor.execute("inspect_data", {"reason": "Inspect values", "view": "values", "column": "amount", **options}))
        assert not result["success"] and result["error_kind"] == "invalid_tool_arguments"



@pytest.mark.parametrize("offset,limit", [(-1, 2), (False, 2), (1.5, 2), (0, 0), (0, 101), (0, True)])
def test_direct_inventory_calls_validate_pagination(offset, limit):
    with pytest.raises(ValueError):
        value_inventory(pd.Series(["A"]), offset, limit)


def test_missing_markers_and_physical_nulls_are_reported_separately():
    result = value_inventory(pd.Series(["N/A", "  ", "missing", None, "valid"]))
    assert result["null_count"] == 1 and result["effective_missing_count"] == 4
    assert result["scanned_rows"] == 5 and result["displayed_value_rows"] == 4


def test_format_groups_keep_bounded_examples_without_losing_full_counts():
    result = value_inventory(pd.Series([str(i) for i in range(1000)]))
    group = result["format_groups"][0]
    assert group["row_count"] == group["distinct_count"] == 1000
    assert len(group["examples"]) == 4
