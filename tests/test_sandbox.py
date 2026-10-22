from pathlib import Path

import pandas as pd

from dataCleaningTools.sandbox import run_dataframe_transform, run_code


def test_fallback_dataframe_transform_copies_input_and_output(tmp_path):
    input_csv = tmp_path / "input.csv"
    pd.DataFrame({"value": [1, 2]}).to_csv(input_csv, index=False)

    result = run_dataframe_transform(
        input_csv,
        'df["value"] = df["value"] + 1',
        backend="fallback",
        output_name="nested/output.csv",
    )

    assert result.success
    output_path = Path(result.metadata["output_files"]["nested/output.csv"])
    assert output_path == Path(result.metadata["work_dir"]) / "output.csv"
    assert pd.read_csv(output_path)["value"].tolist() == [2, 3]
    assert "WROTE 2 rows, 1 cols" in result.stdout


def test_fallback_reports_missing_input_file(tmp_path):
    result = run_code(
        "print('not run')",
        backend="fallback",
        input_files={tmp_path / "missing.csv": "input.csv"},
    )

    assert not result.success
    assert result.error is not None
    assert "Input file missing" in result.error


def test_fallback_rejects_parent_paths_for_files(tmp_path):
    result = run_code(
        "print('not run')",
        backend="fallback",
        input_files={tmp_path / "input.csv": "..\\outside.csv"},
    )

    assert not result.success
    assert result.error is not None
    assert "must be relative" in result.error
