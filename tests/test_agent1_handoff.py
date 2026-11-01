import json

import pytest
from pydantic import ValidationError

from dataCleaningTools.agent1_adapter import parse_profiling_report, resolve_source_path, propose_initial_steps
from dataCleaningTools.models import DatasetReference, ProfilingReport, RiskLevel


def report_data(path="missing.csv"):
    return {"dataset_ref": {"file_path": str(path), "file_name": "input.csv", "rows": 2, "columns": 1},
            "column_profiles": {"amount": {"dtype": "str", "business_interpretation": "Order revenue"}}}


def test_report_inputs_share_one_validated_contract_and_preserve_input(tmp_path):
    raw = report_data()
    raw["column_profiles"]["amount"]["future_profiler_field"] = "ignored"
    raw["future_report_field"] = {"anything": True}
    original = json.dumps(raw)
    file = tmp_path / "report.json"
    file.write_text(original, encoding="utf-8-sig")
    model = parse_profiling_report(raw)
    for payload in (raw, original, file, str(file), model):
        assert parse_profiling_report(payload).model_dump() == model.model_dump()
    assert parse_profiling_report(model) is model
    assert json.dumps(raw) == original and file.read_text(encoding="utf-8-sig") == original
    assert "future_report_field" not in model.model_dump()


def test_long_json_is_not_probed_as_a_filename():
    raw = report_data()
    raw["agent_summary"] = "Evidence " * 20000
    assert parse_profiling_report(json.dumps(raw)).agent_summary == raw["agent_summary"]


def test_missing_files_and_invalid_contracts_are_explicit(tmp_path):
    with pytest.raises(FileNotFoundError):
        parse_profiling_report(tmp_path / "missing.json")
    with pytest.raises(ValidationError):
        parse_profiling_report({"column_profiles": {}})
    with pytest.raises(ValidationError):
        parse_profiling_report('{"dataset_ref": {}}')
    with pytest.raises(TypeError, match="Unsupported payload type"):
        parse_profiling_report(123)


def test_source_resolution_prefers_exact_file_and_falls_back_to_filename(tmp_path):
    exact = tmp_path / "exact.csv"
    exact.write_text("amount\n1\n2\n", encoding="utf-8")
    fallback = tmp_path / "fallback"
    fallback.mkdir()
    (fallback / "input.csv").write_text("amount\n3\n4\n", encoding="utf-8")
    report = parse_profiling_report(report_data(exact))
    assert resolve_source_path(report, [fallback]) == exact.resolve()
    report.dataset_ref.file_path = r"Z:\other-machine\input.csv"
    assert resolve_source_path(report, [fallback]) == (fallback / "input.csv").resolve()
    report.dataset_ref.file_path = str(tmp_path)  # Existing directories are not datasets.
    with pytest.raises(FileNotFoundError, match="Cannot locate dataset"):
        resolve_source_path(report, [tmp_path / "absent"])


def test_baseline_proposals_keep_order_parameters_and_approval_policy():
    report = ProfilingReport.model_validate({**report_data(), "recommended_cleaning_order": ["flag", "amount"],
        "column_profiles": {
            "flag": {"inferred_role": "boolean", "issues": [{"issue_id": "type_mismatch"}]},
            "amount": {"inferred_role": "numeric", "missing_count": 1, "imputation_strategy": "median",
                       "drop_recommended": True, "issues": [{"issue_id": "type_mismatch", "evidence": {"valid_ratio": 50}}]}}})
    before = report.model_dump()
    plan = propose_initial_steps(report, DatasetReference(version="V0", path="unused.csv"))
    assert [s.operation for s in plan.steps] == ["normalize_values", "convert_data_types", "convert_data_types", "handle_missing_values", "drop_column"]
    assert plan.steps[1].parameters == {"target_type": "boolean", "errors": "coerce"}
    assert plan.steps[2].requires_approval
    assert plan.steps[3].parameters == {"strategy": "median"}
    assert plan.steps[-1].requires_approval and plan.overall_risk == RiskLevel.HIGH
    assert all(s.requires_approval or s.risk_level != RiskLevel.HIGH for s in plan.steps)
    assert report.model_dump() == before


def test_explicit_etl_hint_remains_a_single_canonical_cast_proposal():
    report = parse_profiling_report({**report_data(), "etl_hints": {"type_casting_targets": {"amount": "float64"}}})
    plan = propose_initial_steps(report, DatasetReference(version="V0", path="unused.csv"))
    assert len(plan.steps) == 1 and plan.steps[0].parameters["target_type"] == "float"
