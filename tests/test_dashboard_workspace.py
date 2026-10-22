import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

import dashboard.workspace as workspace


def test_upload_dataset_uses_local_storage_and_avoids_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "RAW_DATA", tmp_path)
    first_upload = SimpleNamespace(name="sales.csv", getvalue=lambda: b"amount\n1\n")
    second_upload = SimpleNamespace(name="sales.csv", getvalue=lambda: b"amount\n2\n")

    first = workspace.save_uploaded_dataset(first_upload)
    second = workspace.save_uploaded_dataset(second_upload)

    assert first == tmp_path / "sales.csv"
    assert second == tmp_path / "sales_1.csv"
    assert first.read_bytes() == b"amount\n1\n"
    assert second.read_bytes() == b"amount\n2\n"


def test_analysis_metrics_are_calculated_from_dataframe(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace.st, "session_state", {})
    path = tmp_path / "customers.csv"
    path.write_text("Churn,amount\nYes,10\nNo,20\nYes,30\n,40\n", encoding="utf-8")
    frame = pd.DataFrame(
        {
            "Churn": ["Yes", "No", "Yes", None],
            "amount": [10.0, 20.0, 30.0, 40.0],
        }
    )

    result = workspace.analyze_dataframe(frame, path)

    assert result["rows"] == 4
    assert result["columns"] == 2
    assert result["numeric_columns"] == 1
    assert result["churn_count"] == 2
    assert round(result["churn_rate"], 2) == 66.67


def test_profile_report_verification_checks_saved_content_and_source(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text("value\n1\n", encoding="utf-8")
    report = {
        "dataset_ref": {
            "file_path": str(source.resolve()),
            "rows": 1,
            "columns": 1,
        }
    }
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(report, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    result = {
        "profiling_report": report,
        "report_path": str(report_path),
        "profile": {"rows": 1, "columns": 1},
    }

    verification = workspace.verify_profiling_report(source, result)

    assert verification["verified"] is True
    assert len(verification["sha256"]) == 64

    report_path.write_text('{"tampered": true}', encoding="utf-8")
    verification = workspace.verify_profiling_report(source, result)

    assert verification["verified"] is False
    assert "content" in verification["reason"]
