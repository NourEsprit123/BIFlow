"""Deterministic acceptance checks and measurements for cleaning candidates."""
from __future__ import annotations

import pandas as pd


def present(series: pd.Series) -> pd.Series:
    """Whitespace and common missing markers do not count as populated values."""
    text = series.astype("string").str.strip().str.lower()
    return series.notna() & ~text.isin(["", "n/a", "null", "none", "?", "missing"])


def snapshot(df: pd.DataFrame) -> dict:
    return {
        "rows": len(df), "columns": len(df.columns),
        "missing": {str(c): int((~present(df[c])).sum()) for c in df},
        "dtypes": {str(c): str(df[c].dtype) for c in df},
        "duplicate_rows": int(df.duplicated().sum()),
    }


def target_matches(series: pd.Series, target: str) -> bool:
    target = target.lower()
    # CSV round-trips do not retain pandas' categorical dtype. These hints
    # describe categorical/string values rather than a persisted dtype.
    target = {"str": "string", "object": "string", "category": "string",
              "categorical": "string", "datetime64[ns]": "datetime"}.get(target, target)
    values = series[present(series)]
    if target in ("numeric", "integer", "float", "float64", "int", "int64"):
        numbers = pd.to_numeric(values, errors="coerce")
        return bool(numbers.notna().all() and (
            target not in ("integer", "int", "int64") or numbers.mod(1).eq(0).all()
        ))
    if target in ("datetime", "date"):
        return bool(pd.to_datetime(values, errors="coerce", format="mixed").notna().all())
    if target in ("boolean", "bool"):
        return bool(values.astype(str).str.lower().isin(["true", "false", "1", "0"]).all())
    return target == "string"


def assess_candidate(before: pd.DataFrame, after: pd.DataFrame, operation: str,
                     columns: list[str], parameters: dict) -> dict:
    """Reject unexpected structural changes and loss of populated values."""
    rules = []

    def check(name, passed, message):
        rules.append({"rule_name": name, "passed": bool(passed), "message": message})

    strategy = parameters.get("strategy", "")
    row_removal = operation == "remove_duplicates" or (
        operation == "handle_missing_values" and strategy == "drop_rows")
    column_removal = operation == "drop_column" or (
        operation == "handle_missing_values" and strategy == "drop_columns")
    affected = columns or list(before.columns)
    check("non_empty", not after.empty, f"Candidate contains {len(after)} rows")
    check("row_count", len(after) <= len(before) if row_removal else len(after) == len(before),
          f"Rows: {len(before)} → {len(after)}")
    expected = [c for c in before if c not in affected] if operation == "drop_column" else list(before)
    if operation == "handle_missing_values" and strategy == "drop_columns":
        expected = [c for c in before if c not in affected or not before[c].isna().any()]
    check("columns", list(after) == expected if column_removal else list(after) == list(before),
          "Only explicitly requested columns may be removed")
    changed_cells = None
    changed_examples = []
    if row_removal:
        expected_rows = (before.drop_duplicates(subset=parameters.get("subset") or None,
                                               keep=parameters.get("keep", "first"))
                         if operation == "remove_duplicates"
                         else before.dropna(subset=affected))
        check("retained_rows_unchanged", after.reset_index(drop=True).equals(expected_rows.reset_index(drop=True)),
              "Row removal must preserve the values and order of retained rows")
    if not row_removal and len(before) == len(after):
        changed_cells = 0
        for c in after:
            if c not in before:
                continue
            old, new = before[c].reset_index(drop=True), after[c].reset_index(drop=True)
            same = old.astype("string").eq(new.astype("string")).fillna(False) | (old.isna() & new.isna())
            changed_cells += int((~same).sum())
            for index in same.index[~same][:max(0, 5 - len(changed_examples))]:
                changed_examples.append({"row_position": int(index), "column": str(c),
                                         "before": None if pd.isna(old[index]) else str(old[index])[:200],
                                         "after": None if pd.isna(new[index]) else str(new[index])[:200]})
            check(f"no_new_missing:{c}", not (present(old) & ~present(new)).any(),
                  "Previously populated values must not become missing")
            if c not in affected:
                check(f"untouched:{c}", same.all(), "Unselected column values must stay unchanged")
    if operation in ("convert_data_types", "clean_numeric_string"):
        target = parameters.get("target_type", "numeric")
        for c in affected:
            if c in after:
                check(f"target_type:{c}", target_matches(after[c], target), f"Values must match {target}")
    if operation == "handle_missing_values" and strategy.startswith("fill_"):
        for c in affected:
            if c in after:
                check(f"missing_resolved:{c}", present(after[c]).all(), "Requested imputation must resolve missing values")
    if operation == "remove_duplicates":
        subset = parameters.get("subset") or None
        check("duplicates_resolved", not after.duplicated(subset=subset).any(), "No duplicates remain for the selected key")
    return {
        "accepted": all(r["passed"] for r in rules), "rules": rules,
        "before": snapshot(before), "after": snapshot(after),
        "changed_cells": changed_cells, "rows_removed": len(before) - len(after),
        "changed_examples": changed_examples,
        "columns_removed": [c for c in before if c not in after],
    }
