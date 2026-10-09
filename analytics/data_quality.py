import pandas as pd
import numpy as np
from typing import Dict, Any, List


def load_dataset(file_path: str) -> pd.DataFrame:
    if file_path.endswith('.xlsx') or file_path.endswith('.xls'):
        return pd.read_excel(file_path)
    elif file_path.endswith('.parquet'):
        return pd.read_parquet(file_path)
    else:
        for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252", "iso-8859-1"):
            try:
                return pd.read_csv(file_path, encoding=encoding)
            except (UnicodeDecodeError, ValueError):
                continue
        return pd.read_csv(file_path, encoding="utf-8", errors="replace")


def detect_missing(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Detects missing values (NaN, null strings, whitespace).
    """
    missing = {}
    for column in df.columns:
        nan_count = int(df[column].isna().sum())
        empty_count = 0
        if pd.api.types.is_string_dtype(df[column]) or df[column].dtype == "object":
            empty_count = int(
                df[column]
                .fillna("")
                .astype(str)
                .str.strip()
                .isin(["", "n/a", "null", "none", "?", "missing"])
                .sum()
            )
        total = max(nan_count, empty_count)
        if total > 0:
            missing[column] = total

    total_cells = df.size
    total_missing_cells = sum(missing.values())
    missing_pct = (total_missing_cells / total_cells * 100) if total_cells > 0 else 0.0

    return {
        "columns": missing,
        "total_missing_cells": total_missing_cells,
        "missing_percentage": round(missing_pct, 2)
    }


def detect_duplicates(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Detects duplicate rows.
    """
    duplicate_rows = int(df.duplicated().sum())
    dup_pct = (duplicate_rows / len(df) * 100) if len(df) > 0 else 0.0
    return {
        "count": duplicate_rows,
        "has_duplicates": duplicate_rows > 0,
        "percentage": round(dup_pct, 2)
    }


def detect_type_mismatches(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Detects multiple type issue categories in object/string columns:
    1. Dirty numeric strings   — numeric data stored as object with symbols/text
    2. Date/time stored as str — date-like strings never parsed as datetime
    3. Boolean stored as text  — Yes/No/True/False stored as object
    4. Pseudo-ID columns       — near-unique string columns that look like IDs
    """
    type_issues = {}
    total_rows = len(df)

    # Regex patterns for date detection
    _date_patterns = [
        r'^\d{4}-\d{2}-\d{2}$',           # 2024-01-15
        r'^\d{2}/\d{2}/\d{4}$',            # 01/15/2024
        r'^\d{2}-\d{2}-\d{4}$',            # 15-01-2024
        r'^\d{4}/\d{2}/\d{2}$',            # 2024/01/15
        r'^\d{1,2} \w+ \d{4}$',            # 15 January 2024
    ]
    _bool_values = {"yes", "no", "true", "false", "y", "n", "1", "0", "oui", "non"}

    for col in df.columns:
        if not (pd.api.types.is_string_dtype(df[col]) or df[col].dtype == "object"):
            continue

        series_non_null = df[col].dropna().astype(str).str.strip()
        if len(series_non_null) < 5:
            continue

        nunique = series_non_null.nunique()

        # ── 1. Dirty numeric strings ──────────────────────────────────────────
        coerced = pd.to_numeric(
            series_non_null.str.replace(r'[$€£,\s]', '', regex=True),
            errors='coerce'
        )
        valid_ratio = coerced.notna().sum() / len(series_non_null)
        if 0.80 <= valid_ratio < 1.0:
            dirty_count = int((coerced.isna()).sum())
            type_issues[col] = {
                "valid_numeric_ratio": round(valid_ratio * 100, 2),
                "issue": "Dirty numeric strings (numeric stored as text with symbols/mixed entries)",
                "detected": f"{dirty_count} unparseable entries out of {len(series_non_null)}",
                "recommendation": "Apply 4-level waterfall cleaning → convert to float/int"
            }
            continue  # Don't double-flag the same column

        # ── 2. Date/time stored as string ─────────────────────────────────────
        sample = series_non_null.head(50)
        date_match_ratio = sum(
            sample.str.match(pat, na=False).mean() for pat in _date_patterns
        )
        if date_match_ratio > 0.6:
            type_issues[col] = {
                "valid_numeric_ratio": round(date_match_ratio * 100, 2),
                "issue": "Date/time values stored as plain text (not parsed as datetime)",
                "detected": f"~{round(date_match_ratio * 100)}% of sampled values match date patterns",
                "recommendation": "Parse with pd.to_datetime() to enable time-series operations"
            }
            continue

        # ── 3. Boolean values stored as text ──────────────────────────────────
        if nunique <= 4:
            lower_vals = set(series_non_null.str.lower().unique())
            bool_overlap = lower_vals & _bool_values
            # Only flag as boolean if ALL values are in the boolean set (no extra categories)
            if len(bool_overlap) >= 2 and lower_vals.issubset(_bool_values):
                type_issues[col] = {
                    "valid_numeric_ratio": 100.0,
                    "issue": "Boolean flag stored as text (Yes/No or True/False as object)",
                    "detected": f"Unique values: {sorted(lower_vals)}",
                    "recommendation": "Map to bool dtype: True/False (saves memory, enables logic ops)"
                }
                continue

        # ── 4. Pseudo-ID / near-unique string column ──────────────────────────
        if total_rows >= 50:
            unique_ratio = nunique / total_rows
            if unique_ratio > 0.95 and not any(
                kw in col.lower() for kw in ["name", "desc", "comment", "note", "address"]
            ):
                type_issues[col] = {
                    "valid_numeric_ratio": round(unique_ratio * 100, 2),
                    "issue": "Pseudo-ID column (near-unique string — likely an identifier or key)",
                    "detected": f"{nunique} unique values out of {total_rows} rows ({round(unique_ratio*100,1)}%)",
                    "recommendation": "Exclude from ML features; consider as join key or primary key"
                }

    return type_issues


def detect_outliers(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Detects statistical outliers in numeric columns using IQR method.
    Returns per-column outlier count and bounds.
    """
    outlier_info = {}
    numeric_cols = df.select_dtypes(include="number").columns

    for col in numeric_cols:
        series = df[col].dropna()
        if len(series) < 10:
            continue
        q1  = series.quantile(0.25)
        q3  = series.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        outlier_mask  = (series < lower) | (series > upper)
        outlier_count = int(outlier_mask.sum())
        if outlier_count > 0:
            outlier_info[col] = {
                "outlier_count": outlier_count,
                "outlier_pct": round(outlier_count / len(series) * 100, 2),
                "lower_bound": round(float(lower), 4),
                "upper_bound": round(float(upper), 4),
            }

    return outlier_info


def calculate_health_scores(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Calculates weighted data health score across Completeness, Validity, Uniqueness, Consistency.
    """
    total_rows = len(df)
    total_cells = df.size if total_rows > 0 else 1

    # 1. Completeness
    missing_info = detect_missing(df)
    completeness = max(0.0, 100.0 - missing_info["missing_percentage"])

    # 2. Uniqueness
    dup_info = detect_duplicates(df)
    uniqueness = max(0.0, 100.0 - dup_info["percentage"])

    # 3. Validity (Type mismatches & invalid entries)
    mismatches = detect_type_mismatches(df)
    validity_penalty = len(mismatches) * 5.0
    validity = max(0.0, 100.0 - validity_penalty)

    # 4. Consistency
    consistency = 95.0 if len(mismatches) == 0 else max(70.0, 100.0 - (len(mismatches) * 10.0))

    # 5. Outliers
    outlier_info = detect_outliers(df)

    # Overall Weighted Health Score
    weighted_score = round(
        (completeness * 0.35) +
        (validity * 0.30) +
        (uniqueness * 0.20) +
        (consistency * 0.15),
        1
    )

    return {
        "overall_health_score": weighted_score,
        "completeness": round(completeness, 1),
        "validity": round(validity, 1),
        "uniqueness": round(uniqueness, 1),
        "consistency": round(consistency, 1),
        "missing_info": missing_info,
        "duplicate_info": dup_info,
        "type_issues": mismatches,
        "outlier_info": outlier_info
    }