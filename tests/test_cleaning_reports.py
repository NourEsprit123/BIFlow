import json
from pathlib import Path

import pytest

from agents.dataCleaning_agent import DataCleaningAgent
from dataCleaningTools.models import CleaningResult


@pytest.fixture
def source_report(tmp_path, monkeypatch):
    source = tmp_path / "sales.csv"
    source.write_text("amount\n10\n20\n", encoding="utf-8")
    monkeypatch.setattr("agents.dataCleaning_agent.sandbox_status", lambda: {"selected": "not used"})
    return {"dataset_ref": {"file_path": str(source), "file_name": source.name, "rows": 2, "columns": 1},
            "column_profiles": {"amount": {"dtype": "int64"}}}


def test_cleaning_report_contains_measured_results_and_run_history(tmp_path, source_report):
    agent = DataCleaningAgent(data_root=tmp_path / "versions", use_llm=False)
    first = agent.run(source_report)
    latest = Path(first.metadata["report_path"])
    archive = Path(first.metadata["report_archive_path"])
    assert latest.parent == tmp_path / "reports" / "cleaningReports"
    assert latest.name == "sales_cleaning_report.json"
    saved = CleaningResult.model_validate_json(latest.read_text(encoding="utf-8"))
    assert saved.run_id == first.run_id and saved.validation.all_passed
    summary = saved.metadata["report_summary"]
    assert summary["before"]["rows"] == summary["after"]["rows"] == 2
    assert summary["generated_candidates"] == summary["generated_changes_applied"] == 0
    assert saved.metadata["events"] and saved.source_dataset and saved.final_dataset
    original_archive = archive.read_bytes()
    second = agent.run(source_report)
    assert second.run_id != first.run_id
    assert CleaningResult.model_validate_json(latest.read_text()).run_id == second.run_id
    assert archive.read_bytes() == original_archive
    assert Path(second.metadata["report_archive_path"]).is_file()


def test_failed_runs_export_a_report_without_claiming_success(tmp_path, monkeypatch, source_report):
    source_report["column_profiles"]["amount"]["etl_cast_to"] = "boolean"
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", lambda *a, **k: {
        "tool_calls": [{"id": "finish", "name": "finish", "arguments": {"summary": "Cannot convert charges"}}]})
    result = DataCleaningAgent(data_root=tmp_path / "versions", report_root=tmp_path / "exports",
                               use_llm=True, max_turns=1).run(source_report)
    report = CleaningResult.model_validate_json(Path(result.metadata["report_path"]).read_text())
    assert not report.validation.all_passed
    assert report.metadata["report_summary"]["validation_status"] == "failed"
    assert report.unresolved_issues and report.metadata["events"]


def test_export_failure_does_not_lose_the_saved_cleaning_result(tmp_path, source_report):
    blocked = tmp_path / "not_a_directory"
    blocked.write_text("keep this file", encoding="utf-8")
    result = DataCleaningAgent(data_root=tmp_path / "versions", report_root=blocked,
                               use_llm=False).run(source_report)
    saved = json.loads(Path(result.metadata["result_path"]).read_text())
    assert saved["metadata"]["report_export_error"]
    assert result.validation.all_passed and blocked.read_text() == "keep this file"
