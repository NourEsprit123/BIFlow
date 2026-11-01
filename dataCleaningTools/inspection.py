"""
Inspection tools (read-only).

Agent 2 uses these when the profiling report is insufficient and
needs targeted evidence before deciding on a transformation.
They never modify data.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence
from collections import Counter
from pathlib import Path
import numpy as np
import re

import pandas as pd

from .effects import present
from .models import DatasetReference
from .versioning import DatasetVersionManager


VIEW_FIELDS = {
    "schema": set(), "column": {"column", "limit"}, "patterns": {"column"},
    "values": {"column", "offset", "limit"}, "duplicates": {"column", "subset", "limit"},
    "distribution": {"column"}, "extremes": {"column", "limit"},
    "filtered": {"column", "filter", "threshold", "offset", "limit"},
    "relationships": {"column", "related_column", "limit"},
}


def inspection_query(arguments):
    """One effective query for reading and cache identity; explanations are not data."""
    view = arguments["view"]
    fields = VIEW_FIELDS[view]
    unused = set(arguments) - fields - {"view", "reason", "question", "expected_evidence"}
    if unused:
        raise ValueError(f"view={view} does not use {sorted(unused)}")
    query = {k: v for k, v in arguments.items() if k in fields or k == "view"}
    if "column" in fields and view != "duplicates" and "column" not in query:
        raise ValueError(f"view={view} requires column")
    if "limit" in fields:
        query.setdefault("limit", 50 if view == "values" else 20 if view == "column" else 10)
    if "offset" in fields:
        query.setdefault("offset", 0)
    if view == "duplicates":
        if "column" in query and "subset" in query and query["subset"] != [query["column"]]:
            raise ValueError("Declare duplicate keys with column or subset, not conflicting declarations")
        query["subset"] = sorted(query.get("subset", [query["column"]] if "column" in query else []))
        query.pop("column", None)
    if view == "filtered":
        if "filter" not in query:
            raise ValueError("Filtered inspection requires filter")
        comparison = query["filter"] in {"less_than", "greater_than"}
        if comparison and ("threshold" not in query or not np.isfinite(query["threshold"])):
            raise ValueError("Filtered comparison requires a finite threshold")
        if not comparison and "threshold" in query:
            raise ValueError("threshold is only used by less_than or greater_than")
    if view == "relationships" and (not query.get("related_column") or query["related_column"] == query["column"]):
        raise ValueError("relationships requires a different existing related_column")
    return query


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
                "effective_missing_count": int((~present(df[col])).sum()),
                "null_pct": round(100 * int(df[col].isna().sum()) / len(df), 2) if len(df) else 0.0,
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
    numeric = pd.to_numeric(non_null, errors="coerce")
    numeric = numeric[numeric.notna() & np.isfinite(numeric)]

    return {
        "column": column,
        "version": ref.version,
        "dtype": str(series.dtype),
        "null_count": int(series.isna().sum()),
        "null_pct": round(100 * int(series.isna().sum()) / len(series), 2) if len(series) else 0.0,
        "distinct_count": int(non_null.nunique()),
        "sample_values": non_null.head(sample_size).tolist(),
        "min": float(numeric.min()) if len(numeric) else None,
        "max": float(numeric.max()) if len(numeric) else None,
        "mean": round(float(numeric.mean()), 4) if len(numeric) else None,
        "value_overview": value_inventory(series),
    }


def value_inventory(series, offset=0, limit=50):
    """Scan the whole column; report exactly how much raw-value evidence is shown.

    Format signatures describe syntax only, never a business interpretation.
    Frequency plus rare examples avoids relying on the first rows alone.
    """
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer from 1 to 100")
    values = Counter((type(value).__name__, str(value)) for value in series.dropna())
    ordered = sorted(values.items(), key=lambda item: (-item[1], item[0]))
    entries = [{"value": value, "type": kind, "count": count} for (kind, value), count in ordered[offset:offset+limit]]
    groups = {}
    for (kind, value), count in ordered:
        signature = re.sub(r"\d+", "<digits>", re.sub(r"[^\W\d_]+", "<letters>", value))
        group = groups.setdefault((kind, signature), {"type": kind, "signature": signature, "row_count": 0, "distinct_count": 0, "examples": []})
        group["row_count"] += count
        group["distinct_count"] += 1
        entry = {"value": value, "count": count}
        if group["distinct_count"] <= 4:
            group["examples"].append(entry)
        else:
            group["examples"][2:] = [group["examples"][-1], entry]
    ranked = sorted(groups.values(), key=lambda group: (-group["row_count"], group["type"], group["signature"]))
    # Keep the largest and rarest format groups when the vocabulary is very large.
    selected = ranked if len(ranked) <= 24 else ranked[:12] + ranked[-12:]
    formats = [{"type": group["type"], "signature": group["signature"], "row_count": group["row_count"],
                "distinct_count": group["distinct_count"], "examples": group["examples"]}
               for group in selected]
    non_null = int(series.notna().sum())
    represented = sum(entry["count"] for entry in entries)
    return {"scanned_rows": len(series), "null_count": int(series.isna().sum()),
            "effective_missing_count": int((~present(series)).sum()), "non_null_rows": non_null,
            "distinct_values": len(values), "offset": offset, "limit": limit, "values": entries,
            "displayed_value_rows": represented,
            "displayed_non_null_coverage_pct": round(100 * represented / non_null, 2) if non_null else 100.0,
            "all_distinct_values_displayed": offset == 0 and len(entries) == len(values),
            "next_offset": offset + len(entries) if offset + len(entries) < len(values) else None,
            "format_group_count": len(groups), "format_groups": formats,
            "displayed_format_rows": sum(group["row_count"] for group in selected),
            "missing_pct": round(100 * int(series.isna().sum()) / len(series), 2) if len(series) else 0.0,
            "coverage_meaning": "displayed_non_null_coverage_pct is the percentage of populated rows represented by displayed examples. It is NOT the percentage of non-missing data. Use null_count/missing_pct for physical nulls and effective_missing_count for cleaning missing markers.",
            "note": "Counts scan every row. Displayed values may be partial; low example coverage does not imply missing or invalid data. Format signatures are observations, not parsing rules or proof of meaning."}


def inspect_values(ref, column, offset=0, limit=50, manager=None):
    df = _load(ref, manager)
    if column not in df:
        raise KeyError(f"Column '{column}' not found")
    return {"column": column, "version": ref.version, "value_overview": value_inventory(df[column], offset, limit)}


def inspect_duplicates(
    ref: DatasetReference,
    subset: Optional[Sequence[str]] = None,
    manager: Optional[DatasetVersionManager] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    """Measure exact repeated rows or keys; repetition alone does not authorize deletion."""
    df = _load(ref, manager)
    if subset is not None:
        missing = set(subset) - set(df.columns)
        if missing:
            raise KeyError(f"Subset columns not found: {missing}")

    dup_mask = df.duplicated(subset=list(subset) if subset else None, keep=False)
    n_dup_rows = int(dup_mask.sum())
    duplicate_rows = df.loc[dup_mask]
    n_dup_groups = len(duplicate_rows.drop_duplicates(subset=list(subset) if subset else None))

    return {
        "subset": list(subset) if subset else "all_columns",
        "duplicate_row_count": n_dup_rows,
        "duplicate_group_count": n_dup_groups,
        "redundant_row_count": n_dup_rows - n_dup_groups,
        "sample_duplicate_rows": json_records(duplicate_rows.head(limit)),
        "note": "Repeated keys are observations, not proof that these business records are redundant.",
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

    # Simple pattern heuristics
    patterns = {
        "looks_numeric": series.str.match(r"^-?\d+(\.\d+)?$").sum(),
        "looks_integer": series.str.match(r"^-?\d+$").sum(),
        "looks_date_iso": series.str.match(r"^\d{4}-\d{2}-\d{2}").sum(),
        "looks_date_slash": series.str.match(r"^\d{1,2}/\d{1,2}/\d{2,4}$").sum(),
        "looks_date_dash": series.str.match(r"^\d{1,2}-\d{1,2}-\d{2,4}$").sum(),
        "has_leading_trailing_space": series.str.contains(r"^\s|\s$", regex=True).sum(),
        "empty_string": (series == "").sum(),
    }
    patterns = {k: int(v) for k, v in patterns.items()}

    # Case / whitespace inconsistency for categoricals
    stripped = series.str.strip()
    lower = stripped.str.lower()
    case_variants, variant_groups = {}, 0
    if stripped.nunique() != lower.nunique():
        # Group by lower-case to show variants
        for val, group in stripped.groupby(lower):
            uniq = group.unique().tolist()
            if len(uniq) > 1:
                variant_groups += 1
                if len(case_variants) < 20:
                    case_variants[val] = uniq[:10]

    return {
        "column": column,
        "total_non_null": total, "empty": total == 0,
        "case_variant_group_count": variant_groups,
        "case_variant_limits": {"groups": 20, "variants_per_group": 10},
        "pattern_counts": patterns,
        "pattern_pct": {k: round(v / total * 100, 2) if total else 0.0 for k, v in patterns.items()},
        "case_variants": case_variants,
        "sample_raw": series.head(15).tolist(),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def investigate_column(ref, arguments, manager=None):
    """Targeted full-column measurements; thresholds never certify data errors."""
    frame = _load(ref, manager)
    column, view = arguments["column"], arguments["view"]
    if column not in frame:
        raise ValueError(f"Unknown columns: {column}")
    raw = frame[column].reset_index(drop=True)
    populated = present(raw)
    numeric = pd.to_numeric(raw, errors="coerce")
    if pd.api.types.is_bool_dtype(numeric.dtype):
        numeric = numeric.astype("Int64")
    finite = numeric.notna() & np.isfinite(numeric)
    values = numeric[finite]
    q1, q3 = (float(values.quantile(q)) for q in (.25, .75)) if len(values) else (None, None)
    lower, upper = (q1-1.5*(q3-q1), q3+1.5*(q3-q1)) if len(values) else (None, None)
    outliers = finite & ((numeric < lower) | (numeric > upper)) if len(values) else finite
    limit, offset = arguments.get("limit", 10), arguments.get("offset", 0)
    def examples(selected):
        return [{"row_position": int(i), "row_index": str(frame.index[i]),
                 "value": None if pd.isna(raw.iloc[i]) else str(raw.iloc[i])} for i in selected]
    result = {"column": column, "version": ref.version, "scanned_rows": len(frame),
        "numeric_count": int(finite.sum()), "missing_count": int((~populated).sum()),
        "non_numeric_count": int((populated & numeric.isna()).sum()),
        "non_finite_count": int((numeric.notna() & ~finite).sum()),
        "note": "Numeric measurements use pd.to_numeric on every row. IQR bounds are statistical thresholds, not observed values or proof of errors; business validity requires context."}
    if view == "distribution":
        result.update(min=float(values.min()) if len(values) else None, max=float(values.max()) if len(values) else None,
            median=float(values.median()) if len(values) else None, mean=float(values.mean()) if len(values) else None,
            negative_count=int((finite & (numeric < 0)).sum()), zero_count=int((finite & (numeric == 0)).sum()),
            positive_count=int((finite & (numeric > 0)).sum()),
            q1=q1, q3=q3, iqr_lower_bound=lower, iqr_upper_bound=upper, iqr_outlier_count=int(outliers.sum()))
    elif view == "extremes":
        result.update(smallest=examples(values.nsmallest(limit).index), largest=examples(values.nlargest(limit).index))
    elif view == "filtered":
        kind = arguments.get("filter")
        masks = {"missing": ~populated, "non_numeric": populated & numeric.isna(),
                 "negative": finite & (numeric < 0), "zero": finite & (numeric == 0),
                 "positive": finite & (numeric > 0), "iqr_outliers": outliers}
        if kind in {"less_than", "greater_than"}:
            if "threshold" not in arguments:
                raise ValueError("Filtered comparison requires threshold")
            mask = finite & ((numeric < arguments["threshold"]) if kind == "less_than" else (numeric > arguments["threshold"]))
        elif kind in masks:
            mask = masks[kind]
        else:
            raise ValueError("Filtered inspection requires a supported filter")
        indices = raw.index[mask]
        result.update(filter=kind, matched_rows=len(indices), offset=offset,
                      examples=examples(indices[offset:offset+limit]),
                      next_offset=offset+limit if offset+limit < len(indices) else None)
    elif view == "relationships":
        other = arguments.get("related_column")
        if other not in frame or other == column:
            raise ValueError("relationships requires a different existing related_column")
        second = pd.to_numeric(frame[other].reset_index(drop=True), errors="coerce")
        paired = finite & second.notna() & np.isfinite(second)
        correlation = (numeric[paired].corr(second[paired]) if paired.sum() > 1
                       and numeric[paired].nunique() > 1 and second[paired].nunique() > 1 else float("nan"))
        result.update(related_column=other, numeric_pair_count=int(paired.sum()),
            correlation=None if pd.isna(correlation) else float(correlation),
            examples=json_records(frame[[column, other]].head(limit)),
            relationship_note="Correlation and examples do not establish a business consistency rule or causation.")
    else:
        raise ValueError(f"Unknown numeric inspection view: {view}")
    return result


def json_records(frame):
    import json
    return json.loads(frame.to_json(orient="records", date_format="iso"))

def _load(ref: DatasetReference, manager: Optional[DatasetVersionManager]) -> pd.DataFrame:
    return manager.load(ref) if manager is not None else DatasetVersionManager._read(Path(ref.path), ref.format)
