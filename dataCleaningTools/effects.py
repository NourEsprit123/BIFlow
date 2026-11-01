"""Deterministic acceptance checks and measurements for cleaning candidates."""
from __future__ import annotations

import pandas as pd

MISSING_MARKERS = frozenset({"", "n/a", "null", "none", "?", "missing"})


def present(series: pd.Series) -> pd.Series:
    """Whitespace and common missing markers do not count as populated values."""
    text = series.astype("string").str.strip().str.lower()
    return series.notna() & ~text.isin(MISSING_MARKERS)


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
        # Parseable text is not an already completed numeric conversion. CSV
        # supports numeric dtypes, unlike categorical/datetime metadata.
        if not pd.api.types.is_numeric_dtype(series.dtype) or pd.api.types.is_bool_dtype(series.dtype):
            return False
        numbers = pd.to_numeric(values, errors="coerce")
        return bool(numbers.notna().all() and (
            target not in ("integer", "int", "int64") or numbers.mod(1).eq(0).all()
        ))
    if target in ("datetime", "date"):
        return bool(pd.to_datetime(values, errors="coerce", format="mixed").notna().all())
    if target in ("boolean", "bool"):
        return bool(pd.api.types.is_bool_dtype(series.dtype) or (
            not values.empty and values.map(lambda value: pd.api.types.is_bool_dtype(type(value))).all()))
    return target == "string"


def assess_candidate(before: pd.DataFrame, after: pd.DataFrame, operation: str,
                     columns: list[str], parameters: dict) -> dict:
    """Check structure and declared outcomes; audit populated-to-missing coercions."""
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
        expected = [c for c in before if c not in affected or present(before[c]).all()]
    check("columns", list(after) == expected if column_removal else list(after) == list(before),
          "Only explicitly requested columns may be removed")
    changed_cells = None
    changed_examples = []
    lost_values = []
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
            lost = present(old) & ~present(new)
            for index in lost.index[lost]:
                lost_values.append({"row_position": int(index), "row_index": str(before.index[index]),
                    "column": str(c), "before": str(old[index]),
                    "after": None if pd.isna(new[index]) else str(new[index])})
            if c not in affected:
                check(f"untouched:{c}", same.all(), "Unselected column values must stay unchanged")
    if operation in ("convert_data_types", "clean_numeric_string"):
        target = parameters.get("target_type", "numeric")
        for c in affected:
            if c in after:
                check(f"target_type:{c}", target_matches(after[c], target), f"Values must match {target}")
    if operation == "parse_datetime":
        for c in affected:
            if c in after:
                check(f"target_type:{c}", target_matches(after[c], "datetime"), "Values must match datetime")
    if operation == "standardize_missing" and len(before) == len(after):
        for c in affected:
            if c in after:
                old, new = before[c].reset_index(drop=True), after[c].reset_index(drop=True)
                rewritten = old.astype("string").ne(new.astype("string")).fillna(True) & old.notna()
                check(f"markers_only:{c}", (~present(new[rewritten])).all(),
                      "Only missing markers may change, and only into nulls")
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
        "lost_values": lost_values, "lost_value_count": len(lost_values),
        "columns_removed": [c for c in before if c not in after],
    }


def change_impact(before: pd.DataFrame, after: pd.DataFrame, columns: list[str]) -> dict:
    """What an approval would commit: changed rows and values, separate from dtype-only changes."""
    impact = {"rows": len(before), "rows_after": len(after), "columns_removed": [str(c) for c in before if c not in after]}
    if len(before) != len(after):
        return impact
    changed_rows = pd.Series(False, index=range(len(before)))
    values, dtypes = {}, {}
    for c in columns:
        if c not in before or c not in after:
            continue
        old, new = before[c].reset_index(drop=True), after[c].reset_index(drop=True)
        numeric = all(pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s) for s in (old, new))
        # Numeric equality, so 34 -> 34.0 counts as a dtype change rather than a value change.
        same = (old == new) if numeric else old.astype("string").eq(new.astype("string"))
        diff = ~(same.fillna(False).astype(bool) | (old.isna() & new.isna()))
        values[str(c)] = int(diff.sum())
        changed_rows |= diff
        if str(old.dtype) != str(new.dtype):
            dtypes[str(c)] = f"{old.dtype} -> {new.dtype}"
    impact.update(rows_changed=int(changed_rows.sum()), values_changed=values, dtype_changes=dtypes)
    return impact


def failure_summary(result):
    """Collect all loss evidence, separate from the five general examples."""
    effects = []
    effect = result.get("effect") or (result.get("details") or {}).get("full_data_effect")
    if effect:
        effects.append((None, effect))
    for trial in result.get("trials", []):
        if trial.get("effect"):
            effects.append((trial.get("partition"), trial["effect"]))
    failed, losses = [], []
    for partition, effect in effects:
        scope = {"partition": partition} if partition else {}
        failed.extend({**rule, **scope} for rule in effect.get("rules", []) if not rule["passed"])
        losses.extend({**cell, **scope} for cell in effect.get("lost_values", []))
    errors = [str(result["error"])] if result.get("error") else []
    errors += [f"{rule['rule_name']}: {rule.get('message', '')}" for rule in failed]
    errors += [f"{trial['partition']}: {trial['error']}" for trial in result.get("trials", []) if trial.get("error")]
    reason = "; ".join(dict.fromkeys(errors)) or "Candidate did not pass its required trial checks."
    if losses:
        reason += f" {len(losses)} populated cells would become missing (permitted coercions; see affected values)."
    return {"reason": reason, "failed_checks": failed,
            "lost_value_count": len(losses), "lost_values": losses,
            "next_action": "This candidate failed. Do not apply or repeat it. Inspect the unparsed values or actual failure, revise the method, or flag genuine ambiguity for review."}
