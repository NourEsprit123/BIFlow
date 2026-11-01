"""Read-only value meanings shared by code-writing guidance and acceptance checks.

Only a declared target authorizes an interpretation. No dataset is converted here,
and unknown dates, categories, units and business meanings are never guessed.
"""
import numbers

import pandas as pd

from .contracts import canonical_type
from .inspection import value_inventory
from .effects import MISSING_MARKERS, target_matches
from .numeric_expectations import expected_number


BOOLEAN_VALUES = {"yes": True, "true": True, "y": True, "t": True, "1": True, "1.0": True,
                  "no": False, "false": False, "n": False, "f": False, "0": False, "0.0": False}


def expected_boolean(value):
    if isinstance(value, str):
        return BOOLEAN_VALUES.get(value.strip().casefold())
    if pd.isna(value):
        return None
    if isinstance(value, (bool, numbers.Real)) and value in (0, 1):
        return bool(value)
    # numpy bool is neither Python bool nor Real.
    if pd.api.types.is_bool_dtype(type(value)):
        return bool(value)
    return None


def interpretation(value, target):
    target = canonical_type(target or "")
    if pd.isna(value) or (isinstance(value, str) and value.strip().casefold() in MISSING_MARKERS):
        return {"status": "missing", "expected": None}
    if not target:
        return {"status": "not_applicable", "expected": None,
                "reason": "No conversion target declared. Preserve the value; assess only the active finding."}
    if target == "string":
        return {"status": "preserve", "expected": str(value),
                "reason": "String target does not require decoding identifiers or inventing category meanings."}
    if target == "boolean":
        expected = expected_boolean(value)
    elif target in {"numeric", "float", "integer"}:
        expected = expected_number(value)
        if target == "integer" and expected is not None and not float(expected).is_integer():
            return {"status": "needs_review", "expected": None, "reason": "Fractional value requires a rounding policy"}
    else:
        return {"status": "unsupported", "expected": None,
                "reason": "This layer has no interpreter for the target. Inspect the active finding; lack of an interpreter is not business ambiguity."}
    return {"status": "recognized" if expected is not None else "unresolved", "expected": expected}


def column_plan(series, target, *, limit=20):
    target = canonical_type(target or "")
    conversion_needed = bool(target and not target_matches(series, target))
    inventory = value_inventory(series, limit=limit if conversion_needed else min(limit, 5))
    mappings = [{**entry, **interpretation(entry["value"], target)} for entry in inventory["values"]]
    return {"target": target, "current_dtype": str(series.dtype), "conversion_needed": conversion_needed,
            "scanned_rows": len(series), "null_count": inventory["null_count"],
            "effective_missing_count": inventory["effective_missing_count"],
            "distinct_values": inventory["distinct_values"], "mappings": mappings,
            "all_distinct_values_displayed": inventory["all_distinct_values_displayed"],
            "displayed_non_null_coverage_pct": inventory["displayed_non_null_coverage_pct"],
            "missing_pct": inventory["missing_pct"], "coverage_meaning": inventory["coverage_meaning"],
            "next_offset": inventory["next_offset"],
            "format_groups": inventory["format_groups"],
            "format_group_count": inventory["format_group_count"],
            "guidance": "Use supported mappings when conversion is needed; otherwise preserve the typed values. "
                "Unresolved values need inspection; unsupported targets are not automatic review flags. "
                "Mappings may be partial; format groups include common and rare representations."}


def plans(state, columns, checks=(), *, frame=None):
    if frame is None:
        frame = state.manager.load(state.current_ref)
    targets = {check["column"]: check["kind"] for check in checks
               if check["kind"] in {"boolean", "numeric", "integer", "datetime", "string"}}
    targets.update(state.required_targets)
    result = {"version": state.current_ref.version, "read_only": True,
            "columns": {column: column_plan(frame[column], targets.get(column))
                        for column in columns if column in frame}}
    for column, plan in result["columns"].items():
        state.evidence[f"interpretation:{state.current_ref.version}:{column}"] = {
            "source": "read-only value interpretation", "version": state.current_ref.version,
            "columns": [column], "plan": plan}
    return result


def boolean_rules(before, after, columns):
    """Validate every recognized boolean source value, not just displayed examples."""
    rules = []
    for column in columns:
        if column not in before or column not in after or len(before) != len(after):
            continue
        checked, mismatches = 0, []
        for position, (old, new) in enumerate(zip(before[column], after[column])):
            expected = expected_boolean(old)
            if expected is None:
                continue
            checked += 1
            # Require a real boolean or numeric 0/1, not Python truthiness of strings.
            correct = not pd.isna(new) and (
                pd.api.types.is_bool_dtype(type(new)) or isinstance(new, numbers.Real)) and new == expected
            if not correct:
                mismatches.append({"row_position": position, "row_index": str(before.index[position]),
                    "column": column, "before": str(old), "expected": expected,
                    "actual": None if pd.isna(new) else str(new)})
        if checked:
            rules.append({"rule_name": f"expected:boolean_values:{column}", "passed": not mismatches,
                "message": f"Preserve the boolean meaning of {checked} recognized source values; {len(mismatches)} mismatches",
                "checked_values": checked, "mismatches": mismatches})
    return rules
