from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from dataCleaningTools.models import DatasetStatus
from dataCleaningTools.versioning import DatasetVersionManager


def source_file(tmp_path):
    source = tmp_path / "input.csv"
    pd.DataFrame({"amount": [1, 2]}).to_csv(source, index=False)
    return source


def test_working_copy_uses_known_metadata_without_rereading_dataset(tmp_path, monkeypatch):
    source = source_file(tmp_path)
    manager = DatasetVersionManager(tmp_path / "versions")
    original = manager.register_original(source, dataset_id="sales", metadata={"origin": "profile"})
    def forbidden(*args):
        raise AssertionError("Copying a known version must not parse its data or all metadata again")
    monkeypatch.setattr(manager, "_read", forbidden)
    monkeypatch.setattr(manager, "list_versions", forbidden)
    working = manager.create_working_copy(original)
    assert Path(working.path).read_bytes() == Path(original.path).read_bytes() == source.read_bytes()
    assert working.version == "V1" and working.parent_version == "V0"
    assert working.row_count == 2 and working.columns == ["amount"]
    assert working.created_at >= original.created_at
    working.columns.append("local_only")
    working.metadata["origin"] = "working"
    assert original.columns == ["amount"] and original.metadata["origin"] == "profile"


def test_version_history_is_numeric_and_survives_manager_restart(tmp_path):
    source = source_file(tmp_path)
    manager = DatasetVersionManager(tmp_path / "versions")
    original = manager.register_original(source, dataset_id="sales")
    ref = manager.create_working_copy(original)
    for number in range(2, 13):
        previous = ref
        ref, change = manager.commit_transformation(ref, pd.DataFrame({"amount": [number]}), operation="test", rationale="Synthetic accepted change")
        assert ref.version == f"V{number}" and ref.parent_version == previous.version
        assert change.source_version == previous.version and change.result_version == ref.version
    assert [r.version for r in manager.list_versions("sales")] == [f"V{i}" for i in range(13)]
    reopened = DatasetVersionManager(manager.root)
    ref, _ = reopened.commit_transformation(ref, pd.DataFrame({"amount": [13]}), operation="test")
    assert ref.version == "V13" and reopened.load(ref).amount.tolist() == [13]
    rejected = reopened.record_rejected(ref, operation="test", error_message="Rejected candidate")
    assert rejected.source_version == rejected.result_version == "V13"
    assert len(reopened.list_versions("sales")) == 14
    assert len(reopened.get_changelog("sales").entries) == 13
    validated = reopened.mark_validated(ref)
    assert validated.status == DatasetStatus.VALIDATED and ref.status == DatasetStatus.WORKING
    assert source.read_bytes() == Path(original.path).read_bytes()


def test_registering_an_existing_dataset_never_overwrites_v0(tmp_path):
    source = source_file(tmp_path)
    manager = DatasetVersionManager(tmp_path / "versions")
    original = manager.register_original(source, dataset_id="sales")
    saved = Path(original.path).read_bytes()
    source.write_text("amount\n999\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        manager.register_original(source, dataset_id="sales")
    assert Path(original.path).read_bytes() == saved


def test_invalid_source_or_format_fails_before_registration(tmp_path):
    manager = DatasetVersionManager(tmp_path / "versions")
    with pytest.raises(FileNotFoundError):
        manager.register_original(tmp_path, dataset_id="directory")
    with pytest.raises(ValueError, match="Unsupported format"):
        manager.register_original(source_file(tmp_path), dataset_id="unsupported", format="unknown")
    assert not (manager.root / "unsupported").exists()


def test_new_version_metadata_still_validates_column_contract(tmp_path):
    manager = DatasetVersionManager(tmp_path / "versions")
    original = manager.register_original(source_file(tmp_path), dataset_id="sales")
    working = manager.create_working_copy(original)
    with pytest.raises(ValidationError):
        manager.commit_transformation(working, pd.DataFrame({1: [10]}), operation="test")
    assert [r.version for r in manager.list_versions("sales")] == ["V0", "V1"]
    assert not list((manager.root / "sales").glob("V2_*"))


@pytest.mark.parametrize("fmt", ["csv", "json", "parquet", "xlsx"])
def test_supported_formats_round_trip_versions(tmp_path, fmt):
    if fmt == "parquet":
        pytest.importorskip("pyarrow")
    if fmt == "xlsx":
        pytest.importorskip("openpyxl")
    manager = DatasetVersionManager(tmp_path / "versions")
    source = tmp_path / f"input.{fmt}"
    frame = pd.DataFrame({"amount": [1, 2]})
    manager._write(frame, source, fmt)
    original = manager.register_original(source, dataset_id="sales")
    ref = manager.create_working_copy(original)
    ref, _ = manager.commit_transformation(ref, pd.DataFrame({"amount": [3]}), operation="test")
    assert manager.load(ref).amount.tolist() == [3]
    assert manager.load(original).amount.tolist() == [1, 2]
