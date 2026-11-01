import json
from pathlib import Path

import pandas as pd
import pytest

from dataCleaningTools import experiments, workflow
from dataCleaningTools.numeric_expectations import expected_number
from dataCleaningTools.self_correction import correction_context
from tests.test_cleaning_experiments import session, request, trusted_test_runner


@pytest.mark.parametrize("value,expected", [
    ("$1,200.50", 1200.5), ("1.5k", 1500), ("2.1K", 2100), ("3k", 3000),
    ("2.1m", 2100000), (".75k", 750), ("-2.5k", -2500), ("(£1,200.50)", -1200.5),
    ("1e3", 1000), ("one thousand", 1000), ("five hundred", 500), ("quarter million", 250000),
    ("half a million", 500000), ("one million two hundred thousand", 1200000),
    ("two hundred and thirty-four", 234), ("minus twelve", -12), ("zero", 0),
    ("1.5 million", 1500000), ("a hundred", 100), ("a thousand", 1000),
])
def test_independent_expected_magnitudes(value, expected):
    assert expected_number(value) == expected


@pytest.mark.parametrize("value", ["banana", "ERROR_404", "unknown", "12 monkeys", "one two", "twenty twenty",
    "one thousand million", "1,23", "NaN", None, pd.NA, float("nan"), True, {"amount": 1}])
def test_unknown_content_has_no_invented_expected_value(value):
    assert expected_number(value) is None


def test_magnitude_errors_and_recognizable_coercions_fail_but_invalid_nan_is_allowed():
    before = pd.DataFrame({"amount": ["1.5k", "$450.00", "five hundred", "banana", "ERROR_404"]})
    wrong = pd.DataFrame({"amount": [1.5, None, None, None, None]})
    effect = experiments.assess_method(before, wrong, ["amount"], [{"column": "amount", "kind": "numeric"}])
    assert not effect["accepted"]
    rule = next(r for r in effect["rules"] if r["rule_name"] == "expected:numeric_values:amount")
    assert [(m["before"], m["expected"]) for m in rule["mismatches"]] == [
        ("1.5k", 1500), ("$450.00", 450), ("five hundred", 500)]
    assert not any(r["rule_name"].startswith("no_new_missing:") for r in effect["rules"])
    correct = pd.DataFrame({"amount": [1500, 450, 500, None, None]})
    assert experiments.assess_method(before, correct, ["amount"], [{"column": "amount", "kind": "numeric"}])["accepted"]


def test_every_recognizable_value_is_checked_not_only_first_five():
    before = pd.DataFrame({"amount": ["$10"] * 100 + ["half a million"]})
    after = pd.DataFrame({"amount": [10.0] * 100 + [None]})
    effect = experiments.assess_method(before, after, ["amount"], [{"column": "amount", "kind": "numeric"}])
    rule = next(r for r in effect["rules"] if r["rule_name"] == "expected:numeric_values:amount")
    assert rule["checked_values"] == 101 and rule["mismatches"][0]["row_position"] == 100


def test_missing_task_cannot_overwrite_existing_numeric_values():
    before = pd.DataFrame({"amount": [10.0, None, 30.0]})
    after = pd.DataFrame({"amount": [20.0, 20.0, 20.0]})
    assert not experiments.assess_method(before, after, ["amount"], [{"column": "amount", "kind": "no_missing"}])["accepted"]
    after = pd.DataFrame({"amount": [10.0, 20.0, 30.0]})
    assert experiments.assess_method(before, after, ["amount"], [{"column": "amount", "kind": "no_missing"}])["accepted"]


def test_builtin_trials_check_known_representations_without_model_checks(session):
    state, executor, _ = session
    result = json.loads(executor.execute("test_builtin", {"hypothesis": "Incorrect direct conversion",
        "columns": ["amount"], "operation": "convert_data_types", "parameters": {"target_type": "float"}}))
    assert not result["tested"]
    assert any(r["rule_name"] == "expected:numeric_values:amount" for r in result["failure_summary"]["failed_checks"])
    assert state.current_ref.version == "V1"


def test_full_data_rerun_rejects_semantic_error_after_passing_trials(session, monkeypatch):
    state, executor, evidence = session
    trusted = trusted_test_runner([])
    def sandbox(frame, code, **kwargs):
        result = trusted(frame, code, **kwargs)
        if len(frame) == 4:
            result["df"].loc[0, "amount"] = 10000
        return result
    monkeypatch.setattr(experiments, "run_isolated_transform", sandbox)
    trial = json.loads(executor.execute("test_generated", request(evidence)))
    assert trial["tested"]
    result = json.loads(executor.execute("apply_candidate", {"candidate_id": trial["candidate_id"], "assessment": "Trials passed"}))
    assert not result["success"] and state.current_ref.version == "V1"
    assert "expected:numeric_values:amount" in result["error"]


def test_explicit_domain_transform_does_not_infer_numeric_preservation():
    before = pd.DataFrame({"amount": [10.0]}); after = pd.DataFrame({"amount": [20.0]})
    assert experiments.assess_method(before, after, ["amount"], [{"column": "amount", "kind": "numeric"}],
                                     verify_numeric_values=False)["accepted"]


def test_sandbox_warning_and_specific_fix_reach_local_and_expert_context(session, monkeypatch):
    state, executor, evidence = session
    warning = "ChainedAssignmentError: df[col].fillna(value, inplace=True) does not update the DataFrame (Copy-on-Write)."
    def sandbox(frame, code, **kwargs):
        output = frame.copy(); output["amount"] = pd.to_numeric(output["amount"].str.replace("$", "", regex=False))
        return {"success": True, "df": output, "image_id": "sha256:test", "log": warning}
    monkeypatch.setattr(experiments, "run_isolated_transform", sandbox)
    args = request(evidence)
    result = json.loads(executor.execute("test_generated", args))
    assert not result["success"]
    assert result["recovery_prompt"]["context"]["sandbox_logs"] == [warning]
    context = correction_context(state, executor, args, result, 1, 4, "validation")
    assert context["failure"]["sandbox_logs"] == [warning]
    assert "df[column] = df[column].fillna(value)" in context["failure"]["diagnostic"]["runtime_guidance"]
    from dataCleaningTools.expert_generator import generation_context
    expert = generation_context(executor, args, result, [])
    assert expert["failure"]["sandbox_logs"] == [warning]
    trace = json.loads((Path(state.current_ref.path).parent / "execution_trace.json").read_text())
    assert trace["events"][-1]["result"]["trials"][-1]["log"] == warning
