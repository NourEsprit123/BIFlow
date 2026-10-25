"""Shared data and agent actions for the Streamlit workspace."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from agents.data_engineering_agent import DataEngineeringAgent
from analytics.data_quality import calculate_health_scores, detect_cross_column_issues
from analytics.profiler import load_dataset as _load_dataset
from agents.dataCleaning_agent import DataCleaningAgent
from dataCleaningTools.models import CleaningResult
from dataCleaningTools.agent1_adapter import parse_profiling_report

ROOT = Path(__file__).resolve().parent.parent
RAW_DATA = ROOT / "data" / "raw"
SUPPORTED_SUFFIXES = {".csv", ".xlsx", ".xls", ".parquet"}
DATASET_STATE_KEY = "workspace_dataset_path"
PROFILE_STATE_KEY = "workspace_profile_result"
CLEANING_STATE_KEY = "workspace_cleaning_result"
ANALYSIS_STATE_KEY = "workspace_analysis_result"


def list_datasets() -> list[Path]:
    RAW_DATA.mkdir(parents=True, exist_ok=True)
    return sorted(
        (
            path.resolve()
            for path in RAW_DATA.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
        ),
        key=lambda path: path.name.casefold(),
    )


def dataset_label(path: Path) -> str:
    return path.stem.replace("_", " ").replace("-", " ").title()


def selected_dataset_path() -> Path | None:
    datasets = list_datasets()
    requested = st.session_state.get("workspace_new_dataset_path")
    if requested:
        candidate = Path(requested).resolve()
        if candidate in datasets:
            st.session_state[DATASET_STATE_KEY] = str(candidate)
        st.session_state.pop("workspace_new_dataset_path", None)

    stored = st.session_state.get(DATASET_STATE_KEY)
    if stored:
        selected = Path(stored).resolve()
        if selected in datasets:
            return selected
    if not datasets:
        return None
    default = next((path for path in datasets if path.stem == "telco_churn"), datasets[0])
    st.session_state[DATASET_STATE_KEY] = str(default)
    return default


def load_dataset(path: str) -> pd.DataFrame:
    return _load_dataset(path)


def load_selected_dataset() -> tuple[Path | None, pd.DataFrame | None]:
    path = selected_dataset_path()
    return (path, _load_dataset(str(path))) if path else (None, None)


def save_uploaded_dataset(uploaded_file: Any) -> Path:
    suffix = Path(uploaded_file.name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError("Upload a CSV, Excel, or Parquet dataset.")

    RAW_DATA.mkdir(parents=True, exist_ok=True)
    base = Path(uploaded_file.name).stem.strip() or "dataset"
    destination = RAW_DATA / f"{base}{suffix}"
    counter = 1
    while destination.exists():
        destination = RAW_DATA / f"{base}_{counter}{suffix}"
        counter += 1

    with destination.open("xb") as output:
        output.write(uploaded_file.getvalue())
    return destination.resolve()


def profile_dataset_for_workspace(path: Path, *, refresh: bool = False) -> dict[str, Any]:
    path = path.resolve()
    signature = dataset_signature(path)
    cached = st.session_state.get(PROFILE_STATE_KEY)
    if not refresh and cached and cached.get("signature") == signature:
        return cached["result"]

    result = DataEngineeringAgent().run_audit(str(path))
    st.session_state[PROFILE_STATE_KEY] = {"signature": signature, "result": result}
    st.session_state.pop(CLEANING_STATE_KEY, None)
    return result


def profiling_execution_status(result: dict[str, Any]) -> tuple[bool, str]:
    metadata = result["profiling_report"]["metadata"]
    status = metadata.get("llm_status")
    if status == "llm":
        model = metadata.get("llm_model_used")
        model_suffix = f" ({model})" if model else ""
        return True, f"LLM reasoning used{model_suffix}."
    if status == "mixed":
        return False, "Some profiling batches used rule-based fallback instead of the LLM."
    if status == "fallback":
        return False, "The LLM did not produce usable reasoning; rule-based fallback was used."
    return False, "Profiling LLM execution status is not recorded."


def dataset_signature(path: Path) -> tuple[str, int, int]:
    path = path.resolve()
    return (str(path), path.stat().st_mtime_ns, path.stat().st_size)


def get_workspace_result(key: str, path: Path) -> Any | None:
    state = st.session_state.get(key)
    if isinstance(state, dict) and state.get("signature") == dataset_signature(path):
        return state.get("result")
    if key == CLEANING_STATE_KEY:
        # Recover the latest matching run after a browser refresh or app restart.
        candidates = (ROOT / "data" / "versions" / "dashboard").glob(f"*/{path.stem}/cleaning_result.json")
        for candidate in sorted(candidates, key=lambda p: p.stat().st_mtime_ns, reverse=True):
            try:
                result = CleaningResult.model_validate_json(candidate.read_text(encoding="utf-8"))
                profile = st.session_state.get(PROFILE_STATE_KEY)
                if profile and profile.get("signature") == dataset_signature(path):
                    report = parse_profiling_report(profile["result"]["profiling_report"])
                    fingerprint = hashlib.sha256(json.dumps(report.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
                    if result.metadata.get("profiling_report_hash") != fingerprint:
                        continue
                if result.metadata.get("source_signature") == list(dataset_signature(path)):
                    st.session_state[key] = {"signature": dataset_signature(path), "result": result}
                    return result
            except (ValueError, OSError):
                continue
    return None


def quality_summary(df: pd.DataFrame) -> dict[str, Any]:
    return calculate_health_scores(df)


def analyze_dataframe(df: pd.DataFrame, path: Path) -> dict[str, Any]:
    numeric = df.select_dtypes(include="number")
    categorical_columns = [
        column
        for column in df.columns
        if (
            pd.api.types.is_object_dtype(df[column].dtype)
            or pd.api.types.is_string_dtype(df[column].dtype)
            or isinstance(df[column].dtype, pd.CategoricalDtype)
            or pd.api.types.is_bool_dtype(df[column].dtype)
        )
    ]
    categorical = df[categorical_columns]
    churn_column = next(
        (column for column in df.columns if str(column).strip().casefold() in {"churn", "is_churn"}),
        None,
    )
    churn_rate = None
    churn_count = None
    if churn_column:
        values = df[churn_column].astype("string").str.strip().str.casefold()
        positive = values.isin({"yes", "true", "1", "churn", "churned"})
        valid = values.notna() & values.ne("")
        if valid.any():
            churn_count = int((positive & valid).sum())
            churn_rate = float(churn_count / valid.sum() * 100)

    result = {
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "missing_cells": int(df.isna().sum().sum()),
        "duplicate_rows": int(df.duplicated().sum()),
        "numeric_columns": int(len(numeric.columns)),
        "categorical_columns": int(len(categorical.columns)),
        "numeric_summary": numeric.describe().round(3).to_dict() if not numeric.empty else {},
        "category_summary": {
            str(column): df[column].astype("string").value_counts().head(10).to_dict()
            for column in categorical.columns[:8]
        },
        "churn_column": str(churn_column) if churn_column else None,
        "churn_count": churn_count,
        "churn_rate": churn_rate,
    }
    st.session_state[ANALYSIS_STATE_KEY] = {
        "signature": dataset_signature(path),
        "result": result,
    }
    return result


def clean_profiled_dataset(path: Path, *, approved_step_ids: list[str] | None = None, on_event=None) -> Any:
    result = get_workspace_result(PROFILE_STATE_KEY, path)
    if result is None:
        if on_event:
            on_event({"phase": "profiling report missing · running profiling first", "stage": "profiling"})
        result = profile_dataset_for_workspace(path)

    settings = st.session_state.get("cleaning_run_settings", {})
    agent = DataCleaningAgent(
        max_turns=settings.get("max_turns"),
        max_seconds=settings.get("max_seconds"),
        data_root=ROOT / "data" / "versions" / "dashboard",
        search_roots=[RAW_DATA, ROOT / "data"],
        use_llm=None,
    )
    objective = "Improve data quality for BI analysis while preserving the uploaded original."
    if st.session_state.get("prefer_generated_methods", True):
        objective += (
            " This is an academic experimentation run: propose and test a generated cleaning method "
            "with test_method(kind=generated), review the trial results with review_candidate, and apply only a passing "
            "candidate with apply_candidate. If the isolated runtime is unavailable or "
            "the method fails, explain that result and use registered tools where appropriate."
        )
    cleaning = agent.run(
        result["profiling_report"],
        approved_step_ids=approved_step_ids or [],
        user_request=objective,
        on_event=on_event,
    )
    st.session_state[CLEANING_STATE_KEY] = {
        "signature": dataset_signature(path),
        "result": cleaning,
    }
    return cleaning


def profiling_report_json() -> bytes | None:
    state = st.session_state.get(PROFILE_STATE_KEY)
    if not state:
        return None
    return json.dumps(state["result"]["profiling_report"], indent=2, default=str).encode("utf-8")


def verify_profiling_report(path: Path, result: dict[str, Any]) -> dict[str, Any]:
    report = result["profiling_report"]
    report_path = Path(result["report_path"])
    if not report_path.is_absolute():
        report_path = Path.cwd() / report_path

    if not report_path.is_file():
        return {
            "verified": False,
            "reason": "The generated report file is missing.",
            "sha256": None,
        }

    saved_report = report_path.read_bytes()
    try:
        parsed_saved_report = json.loads(saved_report)
    except json.JSONDecodeError:
        return {
            "verified": False,
            "reason": "The saved report is not valid JSON.",
            "sha256": hashlib.sha256(saved_report).hexdigest(),
            "report_path": str(report_path),
        }
    source_matches = report.get("dataset_ref", {}).get("file_path") == str(path.resolve())
    shape_matches = (
        result["profile"]["rows"] == report.get("dataset_ref", {}).get("rows")
        and result["profile"]["columns"] == report.get("dataset_ref", {}).get("columns")
    )
    content_matches = json.dumps(
        parsed_saved_report, sort_keys=True, separators=(",", ":"), default=str
    ) == json.dumps(report, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(saved_report).hexdigest()
    failures = [
        description
        for passed, description in (
            (source_matches, "dataset source"),
            (shape_matches, "dataset dimensions"),
            (content_matches, "saved report content"),
        )
        if not passed
    ]
    return {
        "verified": not failures,
        "reason": (
            "Source, dimensions, and saved report content match."
            if not failures
            else "Mismatch in " + ", ".join(failures) + "."
        ),
        "sha256": digest,
        "report_path": str(report_path),
    }


def cross_column_issues(df: pd.DataFrame) -> list[dict[str, Any]]:
    return detect_cross_column_issues(df)
