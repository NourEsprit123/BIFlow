"""
Validation tools for Agent 2.

Used after transformations to check schema, quality rules, and
before/after impact. Produces ValidationReport models when requested.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Union

import pandas as pd

from .models import (
    DatasetReference,
    ValidationReport,
    ValidationRuleResult,
    ValidationStatus,
)
from .versioning import DatasetVersionManager


def validate_schema(
    df: pd.DataFrame,
    expected_columns: Optional[Sequence[str]] = None,
    required_columns: Optional[Sequence[str]] = None,
    expected_dtypes: Optional[Dict[str, str]] = None,
    min_rows: int = 1,
) -> Dict[str, Any]:
    """
    Structural checks: presence of columns, optional dtype hints, non-empty.
    """
    rules: List[Dict[str, Any]] = []

    # Row count
    rules.append(
        {
            "rule_name": "min_rows",
            "passed": len(df) >= min_rows,
            "message": f"rows={len(df)} (min={min_rows})",
            "details": {"rows": len(df), "min_rows": min_rows},
        }
    )

    if expected_columns is not None:
        expected = list(expected_columns)
        missing = [c for c in expected if c not in df.columns]
        extra = [c for c in df.columns if c not in expected]
        rules.append(
            {
                "rule_name": "expected_columns",
                "passed": len(missing) == 0,
                "message": "ok" if not missing else f"missing={missing}",
                "details": {"missing": missing, "extra": extra},
            }
        )

    if required_columns is not None:
        missing = [c for c in required_columns if c not in df.columns]
        rules.append(
            {
                "rule_name": "required_columns",
                "passed": len(missing) == 0,
                "message": "ok" if not missing else f"missing={missing}",
                "details": {"missing": missing},
            }
        )

    if expected_dtypes:
        dtype_failures = []
        for col, want in expected_dtypes.items():
            if col not in df.columns:
                dtype_failures.append({"column": col, "error": "missing"})
                continue
            actual = str(df[col].dtype)
            # soft match: numeric, bool, datetime families
            ok = _dtype_matches(actual, want)
            if not ok:
                dtype_failures.append(
                    {"column": col, "expected": want, "actual": actual}
                )
        rules.append(
            {
                "rule_name": "expected_dtypes",
                "passed": len(dtype_failures) == 0,
                "message": "ok" if not dtype_failures else str(dtype_failures),
                "details": {"failures": dtype_failures},
            }
        )

    passed = all(r["passed"] for r in rules)
    return {
        "success": True,
        "passed": passed,
        "rules": rules,
        "schema_ok": passed,
    }


def validate_data_quality(
    df: pd.DataFrame,
    max_null_pct: Optional[Dict[str, float]] = None,
    unique_columns: Optional[Sequence[str]] = None,
    numeric_columns: Optional[Sequence[str]] = None,
    min_numeric_parse_ratio: float = 0.9,
    non_negative_columns: Optional[Sequence[str]] = None,
    allowed_values: Optional[Dict[str, Sequence[Any]]] = None,
) -> Dict[str, Any]:
    """
    Content quality checks beyond bare schema.
    """
    rules: List[Dict[str, Any]] = []

    max_null_pct = max_null_pct or {}
    for col, limit in max_null_pct.items():
        if col not in df.columns:
            rules.append(
                {
                    "rule_name": f"null_pct:{col}",
                    "passed": False,
                    "message": "column missing",
                    "details": {},
                }
            )
            continue
        pct = float(df[col].isna().mean() * 100)
        rules.append(
            {
                "rule_name": f"null_pct:{col}",
                "passed": pct <= limit,
                "message": f"null_pct={pct:.2f} (max={limit})",
                "details": {"null_pct": pct, "max": limit},
            }
        )

    for col in unique_columns or []:
        if col not in df.columns:
            rules.append(
                {
                    "rule_name": f"unique:{col}",
                    "passed": False,
                    "message": "column missing",
                    "details": {},
                }
            )
            continue
        n = len(df)
        nunique = int(df[col].nunique(dropna=True))
        # allow nulls: uniqueness among non-null
        non_null = df[col].dropna()
        ok = len(non_null) == non_null.nunique()
        rules.append(
            {
                "rule_name": f"unique:{col}",
                "passed": ok,
                "message": f"unique={nunique}/{len(non_null)} non-null",
                "details": {"unique": nunique, "non_null": len(non_null)},
            }
        )

    for col in numeric_columns or []:
        if col not in df.columns:
            rules.append(
                {
                    "rule_name": f"numeric_parse:{col}",
                    "passed": False,
                    "message": "column missing",
                    "details": {},
                }
            )
            continue
        parsed = pd.to_numeric(df[col], errors="coerce")
        # ratio among originally non-null
        base = df[col].notna()
        if base.sum() == 0:
            ratio = 1.0
        else:
            ratio = float(parsed[base].notna().mean())
        rules.append(
            {
                "rule_name": f"numeric_parse:{col}",
                "passed": ratio >= min_numeric_parse_ratio,
                "message": f"parseable_ratio={ratio:.2f} (min={min_numeric_parse_ratio})",
                "details": {"ratio": ratio},
            }
        )

    for col in non_negative_columns or []:
        if col not in df.columns:
            continue
        num = pd.to_numeric(df[col], errors="coerce")
        neg = int((num < 0).sum())
        rules.append(
            {
                "rule_name": f"non_negative:{col}",
                "passed": neg == 0,
                "message": f"negative_count={neg}",
                "details": {"negative_count": neg},
            }
        )

    for col, allowed in (allowed_values or {}).items():
        if col not in df.columns:
            continue
        allowed_set = set(allowed)
        bad = df[col].dropna()[~df[col].dropna().isin(allowed_set)]
        rules.append(
            {
                "rule_name": f"allowed_values:{col}",
                "passed": len(bad) == 0,
                "message": f"invalid_count={len(bad)}",
                "details": {
                    "invalid_sample": bad.astype(str).head(5).tolist(),
                    "allowed": list(allowed_set)[:20],
                },
            }
        )

    passed = all(r["passed"] for r in rules) if rules else True
    return {
        "success": True,
        "passed": passed,
        "rules": rules,
        "quality_ok": passed,
    }


def compare_before_after(
    before: pd.DataFrame,
    after: pd.DataFrame,
) -> Dict[str, Any]:
    """
    Summarize impact of a transformation chain.
    """
    row_delta = len(after) - len(before)
    cols_before = set(before.columns)
    cols_after = set(after.columns)
    added_cols = sorted(cols_after - cols_before)
    removed_cols = sorted(cols_before - cols_after)
    shared = sorted(cols_before & cols_after)

    null_deltas = {}
    for col in shared:
        b = float(before[col].isna().mean() * 100)
        a = float(after[col].isna().mean() * 100)
        if abs(a - b) > 0.01:
            null_deltas[col] = {"before_pct": round(b, 2), "after_pct": round(a, 2)}

    dtype_changes = {}
    for col in shared:
        bt, at = str(before[col].dtype), str(after[col].dtype)
        if bt != at:
            dtype_changes[col] = {"before": bt, "after": at}

    return {
        "success": True,
        "rows_before": len(before),
        "rows_after": len(after),
        "row_delta": row_delta,
        "columns_added": added_cols,
        "columns_removed": removed_cols,
        "null_pct_changes": null_deltas,
        "dtype_changes": dtype_changes,
    }


def produce_validation_report(
    ref: DatasetReference,
    schema_result: Optional[Dict[str, Any]] = None,
    quality_result: Optional[Dict[str, Any]] = None,
    extra_rules: Optional[List[Dict[str, Any]]] = None,
) -> ValidationReport:
    """
    Merge schema + quality rule dicts into a ValidationReport model.
    """
    rules: List[ValidationRuleResult] = []
    for block in (schema_result, quality_result):
        if not block:
            continue
        for r in block.get("rules") or []:
            rules.append(
                ValidationRuleResult(
                    rule_name=r.get("rule_name", "unnamed"),
                    passed=bool(r.get("passed")),
                    message=str(r.get("message", "")),
                    details=r.get("details") or {},
                )
            )
    for r in extra_rules or []:
        rules.append(
            ValidationRuleResult(
                rule_name=r.get("rule_name", "unnamed"),
                passed=bool(r.get("passed")),
                message=str(r.get("message", "")),
                details=r.get("details") or {},
            )
        )

    failed = [r for r in rules if not r.passed]
    if not rules:
        status = ValidationStatus.NOT_RUN
    elif not failed:
        status = ValidationStatus.PASSED
    elif len(failed) < len(rules):
        status = ValidationStatus.PARTIAL
    else:
        status = ValidationStatus.FAILED

    schema_ok = True
    quality_ok = True
    if schema_result is not None:
        schema_ok = bool(schema_result.get("passed", schema_result.get("schema_ok", True)))
    if quality_result is not None:
        quality_ok = bool(quality_result.get("passed", quality_result.get("quality_ok", True)))

    return ValidationReport(
        dataset_ref=ref,
        status=status,
        rules=rules,
        schema_ok=schema_ok,
        quality_ok=quality_ok,
        unresolved_issues=[f"{r.rule_name}: {r.message}" for r in failed],
        generated_at=datetime.now(timezone.utc),
    )


def run_standard_validation(
    ref: DatasetReference,
    manager: DatasetVersionManager,
    *,
    expected_columns: Optional[Sequence[str]] = None,
    numeric_columns: Optional[Sequence[str]] = None,
    unique_columns: Optional[Sequence[str]] = None,
    max_null_pct: Optional[Dict[str, float]] = None,
    min_numeric_parse_ratio: float = 0.9,
) -> ValidationReport:
    """One-shot validation used by the agent after cleaning."""
    df = manager.load(ref)
    schema = validate_schema(
        df,
        expected_columns=expected_columns,
        min_rows=1,
    )
    quality = validate_data_quality(
        df,
        max_null_pct=max_null_pct,
        unique_columns=unique_columns,
        numeric_columns=numeric_columns,
        min_numeric_parse_ratio=min_numeric_parse_ratio,
    )
    return produce_validation_report(ref, schema, quality)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dtype_matches(actual: str, expected: str) -> bool:
    exp = expected.lower()
    act = actual.lower()
    if exp in act or act in exp:
        return True
    families = {
        "numeric": ("int", "float", "number", "Int", "Float"),
        "float": ("float",),
        "integer": ("int",),
        "string": ("object", "string", "str"),
        "object": ("object", "string"),
        "bool": ("bool", "boolean"),
        "boolean": ("bool", "boolean"),
        "datetime": ("datetime", "date", "time"),
        "date": ("datetime", "date"),
    }
    for key, tokens in families.items():
        if exp == key or exp in tokens:
            return any(t.lower() in act for t in tokens)
    return False