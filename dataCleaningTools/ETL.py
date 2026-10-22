"""
ETL tools for Agent 2 — reshape, derive, filter, join, aggregate, export.

Design notes:
  - Same result envelope as cleaning (CleaningResult).
  - Joins and aggregations are higher risk; policy/LLM should gate them.
  - Never mutates the original source file; caller commits via VersionManager.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import pandas as pd

from .cleaning import CleaningResult


def select_and_rename_columns(
    df: pd.DataFrame,
    columns: Optional[Sequence[str]] = None,
    rename: Optional[Dict[str, str]] = None,
) -> CleaningResult:
    """
    Keep a subset of columns and/or rename them.

    - columns: order of columns to keep (omit = keep all, then rename)
    - rename: {old_name: new_name}
    """
    work = df.copy()
    rename = rename or {}

    if columns is not None:
        missing = set(columns) - set(work.columns)
        if missing:
            return CleaningResult(False, error=f"Columns not found: {sorted(missing)}")
        work = work.loc[:, list(columns)]

    if rename:
        unknown = set(rename.keys()) - set(work.columns)
        if unknown:
            return CleaningResult(False, error=f"Cannot rename missing columns: {sorted(unknown)}")
        work = work.rename(columns=rename)

    return CleaningResult(
        True,
        df=work,
        affected_rows=0,
        message=f"Selected {len(work.columns)} columns"
        + (f", renamed {len(rename)}" if rename else ""),
        details={
            "columns": list(work.columns),
            "rename": rename,
        },
    )


def filter_rows(
    df: pd.DataFrame,
    expression: Optional[str] = None,
    column: Optional[str] = None,
    operator: Optional[str] = None,
    value: Any = None,
) -> CleaningResult:
    """
    Filter rows either by a simple column op or a restricted pandas query expression.

    Simple form: column + operator + value
      operators: eq, ne, gt, ge, lt, le, in, not_in, contains, isna, notna

    Expression form: pandas query string (e.g. "Quantity > 0 and Region == 'North'").
    Prefer simple form when possible — expressions are harder to audit.
    """
    before = len(df)
    work = df.copy()

    try:
        if expression:
            # query uses DataFrame column names as variables
            mask = work.eval(expression) if False else None  # noqa — use query
            work = work.query(expression, engine="python")
        elif column and operator:
            if column not in work.columns:
                return CleaningResult(False, error=f"Column '{column}' not found")
            op = operator.lower()
            series = work[column]
            if op == "eq":
                mask = series == value
            elif op == "ne":
                mask = series != value
            elif op == "gt":
                mask = series > value
            elif op == "ge":
                mask = series >= value
            elif op == "lt":
                mask = series < value
            elif op == "le":
                mask = series <= value
            elif op == "in":
                mask = series.isin(list(value) if not isinstance(value, (list, tuple, set)) else value)
            elif op == "not_in":
                mask = ~series.isin(list(value) if not isinstance(value, (list, tuple, set)) else value)
            elif op == "contains":
                mask = series.astype(str).str.contains(str(value), na=False)
            elif op == "isna":
                mask = series.isna()
            elif op == "notna":
                mask = series.notna()
            else:
                return CleaningResult(False, error=f"Unknown operator: {operator}")
            work = work.loc[mask]
        else:
            return CleaningResult(
                False,
                error="Provide either expression= or column+operator",
            )
    except Exception as e:
        return CleaningResult(False, error=str(e))

    work = work.reset_index(drop=True)
    affected = before - len(work)
    return CleaningResult(
        True,
        df=work,
        affected_rows=affected,
        message=f"Filtered rows: {before} → {len(work)} (removed {affected})",
        details={
            "expression": expression,
            "column": column,
            "operator": operator,
            "value": value,
            "rows_before": before,
            "rows_after": len(work),
        },
    )


def derive_column(
    df: pd.DataFrame,
    name: str,
    expression: Optional[str] = None,
    source_columns: Optional[Sequence[str]] = None,
    operation: Optional[str] = None,
    fill_value: Any = None,
) -> CleaningResult:
    """
    Create or overwrite a column.

    Modes:
      1) expression — pandas eval, e.g. "Revenue - MonthlyCost"
      2) operation on source_columns:
           concat, sum, mean, min, max, copy (single source)
    """
    if name is None or str(name).strip() == "":
        return CleaningResult(False, error="Column name is required")

    work = df.copy()
    try:
        if expression:
            work[name] = work.eval(expression, engine="python")
        elif operation and source_columns:
            cols = list(source_columns)
            missing = set(cols) - set(work.columns)
            if missing:
                return CleaningResult(False, error=f"Source columns missing: {sorted(missing)}")
            op = operation.lower()
            if op == "copy":
                if len(cols) != 1:
                    return CleaningResult(False, error="copy requires exactly one source column")
                work[name] = work[cols[0]]
            elif op == "concat":
                work[name] = work[cols].astype(str).agg("".join, axis=1)
            elif op == "sum":
                work[name] = work[cols].apply(pd.to_numeric, errors="coerce").sum(axis=1)
            elif op == "mean":
                work[name] = work[cols].apply(pd.to_numeric, errors="coerce").mean(axis=1)
            elif op == "min":
                work[name] = work[cols].apply(pd.to_numeric, errors="coerce").min(axis=1)
            elif op == "max":
                work[name] = work[cols].apply(pd.to_numeric, errors="coerce").max(axis=1)
            else:
                return CleaningResult(False, error=f"Unknown operation: {operation}")
        elif fill_value is not None:
            work[name] = fill_value
        else:
            return CleaningResult(
                False,
                error="Provide expression=, or operation=+source_columns, or fill_value=",
            )
    except Exception as e:
        return CleaningResult(False, error=str(e))

    return CleaningResult(
        True,
        df=work,
        affected_rows=len(work),
        message=f"Derived column '{name}'",
        details={
            "name": name,
            "expression": expression,
            "operation": operation,
            "source_columns": list(source_columns) if source_columns else [],
        },
    )


def join_datasets(
    left: pd.DataFrame,
    right: pd.DataFrame,
    left_on: Union[str, Sequence[str]],
    right_on: Optional[Union[str, Sequence[str]]] = None,
    how: str = "left",
    suffixes: Sequence[str] = ("_x", "_y"),
) -> CleaningResult:
    """
    Join two frames. Prefer left/inner; outer/right are allowed but riskier for BI grain.

    Caller is responsible for loading the right dataset; this function only merges.
    """
    how = how.lower()
    if how not in ("left", "right", "inner", "outer"):
        return CleaningResult(False, error=f"Unsupported join type: {how}")

    right_on = right_on if right_on is not None else left_on
    left_keys = [left_on] if isinstance(left_on, str) else list(left_on)
    right_keys = [right_on] if isinstance(right_on, str) else list(right_on)

    missing_l = set(left_keys) - set(left.columns)
    missing_r = set(right_keys) - set(right.columns)
    if missing_l or missing_r:
        return CleaningResult(
            False,
            error=f"Join keys missing — left: {sorted(missing_l)}, right: {sorted(missing_r)}",
        )

    before = len(left)
    suffix_list = list(suffixes)
    if len(suffix_list) != 2:
        return CleaningResult(False, error=f"suffixes must contain exactly 2 values, got {len(suffix_list)}")

    merge_suffixes: tuple[str, str] = (str(suffix_list[0]), str(suffix_list[1]))

    try:
        merged = left.merge(
            right,
            left_on=left_keys,
            right_on=right_keys,
            how=how,
            suffixes=merge_suffixes,
        )
    except Exception as e:
        return CleaningResult(False, error=str(e))

    return CleaningResult(
        True,
        df=merged,
        affected_rows=abs(len(merged) - before),
        message=f"Join how={how}: left {before} rows → {len(merged)} rows",
        details={
            "how": how,
            "left_on": left_keys,
            "right_on": right_keys,
            "rows_left": before,
            "rows_right": len(right),
            "rows_result": len(merged),
            "columns": list(merged.columns),
        },
    )


def aggregate_data(
    df: pd.DataFrame,
    group_by: Sequence[str],
    aggregations: Dict[str, Union[str, List[str]]],
) -> CleaningResult:
    """
    Group-by aggregation.

    aggregations: {column: "sum"|"mean"|"count"|"min"|"max"|"median"|...}
               or {column: ["sum", "mean"]}

    Example: group_by=["Region"], aggregations={"Revenue": "sum", "OrderID": "count"}
    """
    group_by = list(group_by)
    missing = set(group_by) - set(df.columns)
    if missing:
        return CleaningResult(False, error=f"group_by columns missing: {sorted(missing)}")

    agg_cols = set(aggregations.keys()) - set(df.columns)
    if agg_cols:
        return CleaningResult(False, error=f"Aggregation columns missing: {sorted(agg_cols)}")

    # Normalize agg dict for pandas
    flat: Dict[str, Any] = {}
    for col, funcs in aggregations.items():
        if isinstance(funcs, str):
            flat[col] = funcs
        else:
            flat[col] = list(funcs)

    try:
        grouped = df.groupby(group_by, dropna=False).agg(flat)
        # Flatten MultiIndex columns if needed
        if isinstance(grouped.columns, pd.MultiIndex):
            grouped.columns = [
                "_".join(str(c) for c in col).strip("_") for col in grouped.columns
            ]
        grouped = grouped.reset_index()
    except Exception as e:
        return CleaningResult(False, error=str(e))

    return CleaningResult(
        True,
        df=grouped,
        affected_rows=len(grouped),
        message=f"Aggregated to {len(grouped)} groups by {group_by}",
        details={
            "group_by": group_by,
            "aggregations": aggregations,
            "rows_out": len(grouped),
        },
    )


def export_dataset(
    df: pd.DataFrame,
    path: Union[str, Path],
    format: Optional[str] = None,
) -> CleaningResult:
    """
    Write the dataframe to disk (csv / parquet / excel / json).
    Does not change the in-memory df; returns path in details.
    """
    path = Path(path)
    fmt = (format or path.suffix.lstrip(".") or "csv").lower()
    if fmt == "xlsx":
        fmt = "excel"

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "csv":
            df.to_csv(path, index=False)
        elif fmt == "parquet":
            df.to_parquet(path, index=False)
        elif fmt == "excel":
            df.to_excel(path, index=False)
        elif fmt == "json":
            df.to_json(path, orient="records", indent=2)
        else:
            return CleaningResult(False, error=f"Unsupported export format: {fmt}")
    except Exception as e:
        return CleaningResult(False, error=str(e))

    return CleaningResult(
        True,
        df=df,
        affected_rows=len(df),
        message=f"Exported {len(df)} rows to {path}",
        details={
            "path": str(path.resolve()),
            "format": fmt,
            "rows": len(df),
            "columns": list(df.columns),
        },
    )