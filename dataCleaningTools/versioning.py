"""
Dataset versioning for Agent 2.

Design principles:
  - V0 (original) is immutable.
  - Every transformation produces a new version (or a recoverable checkpoint).
  - Physical copies are used initially for safety; copy-on-write can be added later.
  - Full lineage is recorded so the BI Auditor / XAI agent can explain changes.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

import pandas as pd

from .models import (
    ChangeLog,
    ChangeRecord,
    DatasetReference,
    DatasetStatus,
)


class DatasetVersionManager:
    """
    Manages versioned copies of a dataset under a single root directory.

    Layout (example):
        data/
          <dataset_id>/
            V0_original.csv
            V0_meta.json
            V1_working.csv
            V1_meta.json
            V2_...
            changelog.json
    """

    def __init__(self, root: str | Path = "data"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_original(
        self,
        source_path: str | Path,
        dataset_id: Optional[str] = None,
        format: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DatasetReference:
        """
        Ingest an external file as immutable V0.
        Copies the file into the managed store; never modifies the source.
        """
        source_path = Path(source_path)
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source_path}")

        dataset_id = dataset_id or str(uuid4())
        fmt = format or source_path.suffix.lstrip(".").lower() or "csv"
        if fmt == "xlsx":
            fmt = "excel"

        dest_dir = self.root / dataset_id
        dest_dir.mkdir(parents=True, exist_ok=True)

        dest_path = dest_dir / f"V0_original.{self._ext(fmt)}"
        shutil.copy2(source_path, dest_path)

        # Read lightweight stats
        df = self._read(dest_path, fmt)
        ref = DatasetReference(
            dataset_id=dataset_id,
            version="V0",
            path=str(dest_path.resolve()),
            format=fmt,
            row_count=len(df),
            column_count=len(df.columns),
            columns=list(df.columns),
            status=DatasetStatus.ORIGINAL,
            metadata=metadata or {},
        )
        self._write_meta(dest_dir, "V0", ref)
        self._init_changelog(dataset_id)
        return ref

    def create_working_copy(
        self,
        source_ref: DatasetReference,
        label: str = "working",
    ) -> DatasetReference:
        """
        Create the first mutable working version (usually V1) from any prior version.
        """
        return self._new_version(
            source_ref,
            status=DatasetStatus.WORKING,
            label=label,
        )

    def commit_transformation(
        self,
        source_ref: DatasetReference,
        df: pd.DataFrame,
        operation: str,
        columns: Optional[List[str]] = None,
        parameters: Optional[Dict[str, Any]] = None,
        rationale: str = "",
        affected_rows: Optional[int] = None,
        step_id: Optional[str] = None,
        approval_obtained: bool = False,
        success: bool = True,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> tuple[DatasetReference, ChangeRecord]:
        """
        Persist a transformed DataFrame as a new version and append a ChangeRecord.
        Returns (new_ref, change_record).
        """
        new_ref = self._new_version(
            source_ref,
            status=DatasetStatus.WORKING,
            df=df,
        )

        record = ChangeRecord(
            step_id=step_id,
            operation=operation,
            columns=columns or [],
            source_version=source_ref.version,
            result_version=new_ref.version,
            parameters=parameters or {},
            rationale=rationale,
            affected_rows=affected_rows,
            success=success,
            error_message=error_message,
            approval_obtained=approval_obtained,
            metadata=metadata or {},
        )
        self._append_change(source_ref.dataset_id, record)
        return new_ref, record

    def record_rejected(self, ref: DatasetReference, **details) -> ChangeRecord:
        """Keep rejected attempts in the audit trail without changing the dataset."""
        record = ChangeRecord(source_version=ref.version, result_version=ref.version,
                              success=False, **details)
        self._append_change(ref.dataset_id, record)
        return record

    def mark_validated(
        self,
        ref: DatasetReference,
        status: DatasetStatus = DatasetStatus.VALIDATED,
    ) -> DatasetReference:
        """Update the status of an existing version (e.g. after successful validation)."""
        if status not in (DatasetStatus.VALIDATED, DatasetStatus.FAILED):
            raise ValueError("mark_validated only accepts VALIDATED or FAILED")
        dest_dir = self.root / ref.dataset_id
        updated = ref.model_copy(update={"status": status})
        self._write_meta(dest_dir, ref.version, updated)
        return updated

    def load(self, ref: DatasetReference) -> pd.DataFrame:
        """Load a versioned dataset into a DataFrame."""
        return self._read(Path(ref.path), ref.format)

    def get_changelog(self, dataset_id: str) -> ChangeLog:
        path = self.root / dataset_id / "changelog.json"
        if not path.exists():
            return ChangeLog(dataset_id=dataset_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        return ChangeLog.model_validate(data)

    def list_versions(self, dataset_id: str) -> List[DatasetReference]:
        dest_dir = self.root / dataset_id
        if not dest_dir.exists():
            return []
        refs = []
        for meta_file in sorted(dest_dir.glob("*_meta.json")):
            data = json.loads(meta_file.read_text(encoding="utf-8"))
            refs.append(DatasetReference.model_validate(data))
        return refs

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _new_version(
        self,
        source_ref: DatasetReference,
        status: DatasetStatus,
        df: Optional[pd.DataFrame] = None,
        label: str = "",
    ) -> DatasetReference:
        dest_dir = self.root / source_ref.dataset_id
        dest_dir.mkdir(parents=True, exist_ok=True)

        next_ver = self._next_version_label(source_ref.dataset_id)
        fmt = source_ref.format
        dest_path = dest_dir / f"{next_ver}_{label or 'transform'}.{self._ext(fmt)}"

        if df is None:
            # pure copy
            shutil.copy2(source_ref.path, dest_path)
            df = self._read(dest_path, fmt)
        else:
            self._write(df, dest_path, fmt)

        ref = DatasetReference(
            dataset_id=source_ref.dataset_id,
            version=next_ver,
            path=str(dest_path.resolve()),
            format=fmt,
            row_count=len(df),
            column_count=len(df.columns),
            columns=list(df.columns),
            parent_version=source_ref.version,
            status=status,
            metadata=dict(source_ref.metadata),
        )
        self._write_meta(dest_dir, next_ver, ref)
        return ref

    def _next_version_label(self, dataset_id: str) -> str:
        existing = self.list_versions(dataset_id)
        if not existing:
            return "V1"
        nums = []
        for r in existing:
            try:
                nums.append(int(r.version.lstrip("Vv")))
            except ValueError:
                continue
        return f"V{max(nums) + 1}" if nums else "V1"

    def _write_meta(self, dest_dir: Path, version: str, ref: DatasetReference) -> None:
        path = dest_dir / f"{version}_meta.json"
        path.write_text(ref.model_dump_json(indent=2), encoding="utf-8")

    def _init_changelog(self, dataset_id: str) -> None:
        path = self.root / dataset_id / "changelog.json"
        if not path.exists():
            log = ChangeLog(dataset_id=dataset_id)
            path.write_text(log.model_dump_json(indent=2), encoding="utf-8")

    def _append_change(self, dataset_id: str, record: ChangeRecord) -> None:
        log = self.get_changelog(dataset_id)
        log.add(record)
        path = self.root / dataset_id / "changelog.json"
        path.write_text(log.model_dump_json(indent=2), encoding="utf-8")

    @staticmethod
    def _ext(fmt: str) -> str:
        mapping = {"csv": "csv", "parquet": "parquet", "excel": "xlsx", "json": "json"}
        return mapping.get(fmt.lower(), "csv")

    @staticmethod
    def _read(path: Path, fmt: str) -> pd.DataFrame:
        fmt = fmt.lower()
        if fmt == "csv":
            return pd.read_csv(path)
        if fmt in ("excel", "xlsx"):
            return pd.read_excel(path)
        if fmt == "parquet":
            return pd.read_parquet(path)
        if fmt == "json":
            return pd.read_json(path)
        raise ValueError(f"Unsupported format: {fmt}")

    @staticmethod
    def _write(df: pd.DataFrame, path: Path, fmt: str) -> None:
        fmt = fmt.lower()
        if fmt == "csv":
            df.to_csv(path, index=False)
        elif fmt in ("excel", "xlsx"):
            df.to_excel(path, index=False)
        elif fmt == "parquet":
            df.to_parquet(path, index=False)
        elif fmt == "json":
            df.to_json(path, orient="records", indent=2)
        else:
            raise ValueError(f"Unsupported format: {fmt}")