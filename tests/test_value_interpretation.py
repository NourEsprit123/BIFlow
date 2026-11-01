import json
from pathlib import Path

import pandas as pd
import pytest

from dataCleaningTools import experiments
from dataCleaningTools.value_interpretation import column_plan, interpretation, expected_boolean
from dataCleaningTools.tool_registry import AgentSessionState, ToolExecutor
from dataCleaningTools.versioning import DatasetVersionManager
from tests.test_cleaning_tasks import focused


@pytest.mark.parametrize("raw,expected", [("yes", True), ("YES", True), (" Yes ", True),
    ("True", True), (1, True), (True, True), ("NO", False), ("False", False), (0, False),
    (False, False), ("0.0", False), ("1.0", True), ("banana", None), (2, None), (None, None)])
def test_supported_boolean_meanings(raw, expected):
    assert expected_boolean(raw) is expected


def test_plan_is_read_only_counts_raw_variants_and_does_not_guess_context():
    values = pd.Series(["Yes", "Yes", "YES", "No", "banana", None])
    original = values.copy(deep=True)
    plan = column_plan(values, "boolean")
    mappings = {m["value"]: m for m in plan["mappings"]}
    assert mappings["Yes"]["count"] == 2 and mappings["YES"]["expected"] is True
    assert mappings["No"]["expected"] is False
    assert mappings["banana"]["status"] == "unresolved"
    assert plan["null_count"] == 1 and plan["all_distinct_values_displayed"]
    pd.testing.assert_series_equal(values, original)
    assert interpretation("1", "float")["expected"] == 1.0
    assert interpretation("1", "string")["status"] == "preserve"
    assert interpretation("01/02/2026", "datetime")["status"] == "unsupported"
    assert interpretation("1.5", "integer")["status"] == "needs_review"


def test_identifiers_without_conversion_target_are_not_review_flags():
    assert interpretation("ORD_000015-1", None)["status"] == "not_applicable"
    result = interpretation("ORD_000015-1", "string")
    assert result["status"] == "preserve" and result["expected"] == "ORD_000015-1"
    assert interpretation("Yes", "boolean")["expected"] is True
    assert interpretation("banana", "float")["status"] == "unresolved"


def test_partial_plan_reports_coverage():
    plan = column_plan(pd.Series([str(i) for i in range(120)]), "float", limit=10)
    assert not plan["all_distinct_values_displayed"] and plan["next_offset"] == 10
    assert plan["scanned_rows"] == 120 and len(plan["mappings"]) == 10


@pytest.mark.parametrize("wrong", [pd.Series([pd.NA, pd.NA], dtype="boolean"), pd.Series([False, True])])
def test_dtype_alone_cannot_pass_or_reverse_known_meanings(wrong):
    before = pd.DataFrame({"flag": ["Yes", "No"]})
    after = pd.DataFrame({"flag": wrong})
    effect = experiments.assess_method(before, after, ["flag"], [{"column": "flag", "kind": "boolean"}])
    rule = next(r for r in effect["rules"] if r["rule_name"] == "expected:boolean_values:flag")
    assert not effect["accepted"] and len(rule["mismatches"]) == 2
    assert rule["mismatches"][0]["expected"] is True


def test_invalid_values_can_be_missing_without_erasing_known_booleans():
    before = pd.DataFrame({"flag": ["YES", "no", "banana", None]})
    after = pd.DataFrame({"flag": pd.Series([True, False, pd.NA, pd.NA], dtype="boolean")})
    assert experiments.assess_method(before, after, ["flag"], [{"column": "flag", "kind": "boolean"}])["accepted"]


def test_active_task_receives_plan_and_audit_evidence(focused):
    from dataCleaningTools.cleaning_tasks import model_view
    state, executor, _ = focused
    view = model_view(state, executor)
    assert "columns" not in view["value_interpretation"]  # Formatting does not need parser mappings.
    state.cleaning_tasks = [t for t in state.cleaning_tasks if t["columns"] != ["region"]]
    view = model_view(state, executor)
    assert list(view["value_interpretation"]["columns"]) == ["amount"]
    assert "interpretation:V1:amount" in state.evidence


def test_full_data_boolean_check_blocks_bad_promotion(tmp_path, monkeypatch):
    path = tmp_path / "flags.csv"
    pd.DataFrame({"flag": ["Yes", "No", "YES", "NO", "Yes", "No"]}).to_csv(path, index=False)
    manager = DatasetVersionManager(tmp_path / "versions")
    source = manager.register_original(path, dataset_id="flags")
    state = AgentSessionState(manager=manager, dataset_id="flags", source_ref=source,
        current_ref=manager.create_working_copy(source), expected_columns=["flag"], required_targets={"flag": "boolean"})
    executor = ToolExecutor(state)
    original = Path(state.source_ref.path).read_bytes()
    def sandbox(frame, code, **kwargs):
        result = frame.copy()
        result["flag"] = frame.flag.str.lower().map({"yes": True, "no": False}).astype("boolean")
        if len(frame) == 6:
            result["flag"] = pd.Series(pd.NA, index=frame.index, dtype="boolean")
        return {"success": True, "df": result, "image_id": "sha256:test", "repeatable": True}
    monkeypatch.setattr(experiments, "run_isolated_transform", sandbox)
    trial = json.loads(executor.execute("test_generated", {"columns": ["flag"], "hypothesis": "Map actual flag spellings",
        "code": "def transform(df):\n    df['flag'] = df['flag'].str.lower().map({'yes': True, 'no': False}).astype('boolean')\n    return df",
        "checks": [{"column": "flag", "kind": "boolean"}]}))
    assert trial["success"]
    result = json.loads(executor.execute("apply_candidate", {"candidate_id": trial["candidate_id"], "assessment": "Check all rows"}))
    assert not result["success"] and state.current_ref.version == "V1"
    assert Path(state.source_ref.path).read_bytes() == original
    assert any(r["rule_name"] == "expected:boolean_values:flag" and not r["passed"]
               for r in result["details"]["full_data_effect"]["rules"])


@pytest.mark.parametrize("value", [" N/A ", "NULL", "None", "?", "missing", ""])
def test_missing_markers_agree_with_independent_checks(value):
    from dataCleaningTools.effects import present
    assert not present(pd.Series([value])).iloc[0]
    assert interpretation(value, "numeric")["status"] == "missing"
    plan = column_plan(pd.Series([value, None, "12"]), "numeric")
    assert plan["null_count"] == 1 and plan["effective_missing_count"] == 2


def test_already_typed_values_need_no_conversion_and_keep_partial_coverage_explicit():
    plan = column_plan(pd.Series(range(120)), "integer")
    assert not plan["conversion_needed"] and len(plan["mappings"]) == 5
    assert not plan["all_distinct_values_displayed"]
    assert plan["scanned_rows"] == 120 and plan["next_offset"] == 5


def test_rare_formats_are_visible_when_frequent_mapping_examples_are_limited():
    plan = column_plan(pd.Series(["12"] * 100 + ["$1,200"]), "numeric", limit=1)
    assert plan["conversion_needed"] and len(plan["mappings"]) == 1
    assert any(e["value"] == "$1,200" for g in plan["format_groups"] for e in g["examples"])
    assert plan["format_group_count"] == 2
