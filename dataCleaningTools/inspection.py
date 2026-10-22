"""
Inspection tools (read-only).

Agent 2 uses these when the profiling report is insufficient and
needs targeted evidence before deciding on a transformation.
They never modify data.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

import pandas as pd

from .models import DatasetReference
from .versioning import DatasetVersionManager


def inspect_schema(
    ref: DatasetReference,
    manager: Optional[DatasetVersionManager] = None,
) -> Dict[str, Any]:
    """Return column names, dtypes, shape and basic null counts."""
    df = _load(ref, manager)
    return {
        "dataset_id": ref.dataset_id,
        "version": ref.version,
        "shape": {"rows": len(df), "columns": len(df.columns)},
        "columns": [
            {
                "name": col,
                "dtype": str(df[col].dtype),
                "null_count": int(df[col].isna().sum()),
                "null_pct": round(float(df[col].isna().mean()) * 100, 2),
            }
            for col in df.columns
        ],
    }


def inspect_column(
    ref: DatasetReference,
    column: str,
    sample_size: int = 20,
    manager: Optional[DatasetVersionManager] = None,
) -> Dict[str, Any]:
    """Sample values, type info, nulls, distinct count and value distribution."""
    df = _load(ref, manager)
    if column not in df.columns:
        raise KeyError(f"Column '{column}' not found. Available: {list(df.columns)}")

    series = df[column]
    non_null = series.dropna()
    value_counts = non_null.astype(str).value_counts().head(15)

    return {
        "column": column,
        "dtype": str(series.dtype),
        "null_count": int(series.isna().sum()),
        "null_pct": round(float(series.isna().mean()) * 100, 2),
        "distinct_count": int(non_null.nunique()),
        "sample_values": non_null.head(sample_size).tolist(),
        "top_values": [
            {"value": k, "count": int(v)} for k, v in value_counts.items()
        ],
        "min": _safe_stat(non_null, "min"),
        "max": _safe_stat(non_null, "max"),
        "mean": _safe_stat(non_null, "mean"),
    }


def inspect_duplicates(
    ref: DatasetReference,
    subset: Optional[Sequence[str]] = None,
    manager: Optional[DatasetVersionManager] = None,
) -> Dict[str, Any]:
    """Detect full-row or key-based duplicates."""
    df = _load(ref, manager)
    if subset is not None:
        missing = set(subset) - set(df.columns)
        if missing:
            raise KeyError(f"Subset columns not found: {missing}")

    dup_mask = df.duplicated(subset=list(subset) if subset else None, keep=False)
    n_dup_rows = int(dup_mask.sum())
    n_dup_groups = int(df[dup_mask].duplicated(subset=list(subset) if subset else None).sum()) if n_dup_rows else 0

    return {
        "subset": list(subset) if subset else "all_columns",
        "duplicate_row_count": n_dup_rows,
        "approx_duplicate_groups": n_dup_groups,
        "sample_duplicate_rows": df[dup_mask].head(10).to_dict(orient="records") if n_dup_rows else [],
    }


def check_value_patterns(
    ref: DatasetReference,
    column: str,
    manager: Optional[DatasetVersionManager] = None,
) -> Dict[str, Any]:
    """
    Inspect formats / inconsistent representations for a column.
    Useful for dates, numeric-looking strings, categorical labels, etc.
    """
    df = _load(ref, manager)
    if column not in df.columns:
        raise KeyError(f"Column '{column}' not found")

    series = df[column].dropna().astype(str)
    total = len(series)
    if total == 0:
        return {"column": column, "empty": True}

    # Simple pattern heuristics
    patterns = {
        "looks_numeric": series.str.match(r"^-?\d+(\.\d+)?$").sum(),
        "looks_integer": series.str.match(r"^-?\d+$").sum(),
        "looks_date_iso": series.str.match(r"^\d{4}-\d{2}-\d{2}").sum(),
        "looks_date_slash": series.str.match(r"^\d{1,2}/\d{1,2}/\d{2,4}$").sum(),
        "looks_date_dash": series.str.match(r"^\d{1,2}-\d{1,2}-\d{2,4}$").sum(),
        "has_leading_trailing_space": series.str.match(r"^\s+|\s+$").sum(),
        "empty_string": (series == "").sum(),
    }
    patterns = {k: int(v) for k, v in patterns.items()}

    # Case / whitespace inconsistency for categoricals
    stripped = series.str.strip()
    lower = stripped.str.lower()
    case_variants = {}
    if stripped.nunique() != lower.nunique():
        # Group by lower-case to show variants
        for val, group in stripped.groupby(lower):
            uniq = group.unique().tolist()
            if len(uniq) > 1:
                case_variants[val] = uniq

    return {
        "column": column,
        "total_non_null": total,
        "pattern_counts": patterns,
        "pattern_pct": {k: round(v / total * 100, 2) for k, v in patterns.items()},
        "case_variants": case_variants,
        "sample_raw": series.head(15).tolist(),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load(ref: DatasetReference, manager: Optional[DatasetVersionManager]) -> pd.DataFrame:
    if manager is not None:
        return manager.load(ref)
    # Fallback: direct read (useful in tests)
    path = ref.path
    fmt = ref.format.lower()
    if fmt == "csv":
        return pd.read_csv(path)
    if fmt in ("excel", "xlsx"):
        return pd.read_excel(path)
    if fmt == "parquet":
        return pd.read_parquet(path)
    raise ValueError(f"Cannot load format {fmt} without a manager")


def _safe_stat(series: pd.Series, how: str) -> Any:
    try:
        numeric = pd.to_numeric(series, errors="coerce").dropna()
        if numeric.empty:
            return None
        if how == "min":
            return float(numeric.min())
        if how == "max":
            return float(numeric.max())
        if how == "mean":
            return round(float(numeric.mean()), 4)
    except Exception:
        return None
    return None