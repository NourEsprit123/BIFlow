"""Inspect → test on a copy → apply → finish. No stage machine or issue ledger."""
from __future__ import annotations

import json
import time
from pathlib import Path
import pandas as pd
from jsonschema import Draft202012Validator
from . import cleaning
from .contracts import canonical_type
from .effects import assess_candidate, failure_summary
from .experiments import assess_method, digest, experiment
from .method_catalog import SCHEMAS as METHOD_SCHEMAS

CATALOG = ("trim_whitespace", "normalize_values", "convert_data_types", "clean_numeric_string", "handle_missing_values",
           "parse_datetime", "standardize_missing", "remove_duplicates", "handle_outliers")
PER_COLUMN = {"convert_data_types", "clean_numeric_string", "normalize_values", "parse_datetime"}
ROW_REMOVAL = {"remove_duplicates"}
CHECK_KIND = {"numeric": "numeric", "float": "numeric", "integer": "integer", "boolean": "boolean",
              "datetime": "datetime", "string": "string"}
STRING = {"type": "string", "minLength": 1, "pattern": r"\S"}
STRINGS = {"type": "array", "items": STRING, "minItems": 1, "uniqueItems": True}
CHECKS = {"type": "array", "minItems": 1, "items": {"type": "object", "additionalProperties": False,
    "properties": {"column": STRING, "kind": {"type": "string", "enum": ["no_missing", "unique", "non_negative",
        "numeric", "integer", "boolean", "datetime", "string", "preserve_missing"]}}, "required": ["column", "kind"]}}


def tool(name, description, properties, required):
    return {"type": "function", "function": {"name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required, "additionalProperties": False}}}


METHOD_FIELDS = {
    "hypothesis": {**STRING, "description": "Explain evidence, the implemented rule, expected effect and important assumptions concisely."},
    "columns": {**STRINGS, "description": "Target columns, always at the top level."},
    "checks": CHECKS,
    "value_assessment": {"type": "object", "additionalProperties": False,
        "properties": {k: STRING for k in ("evidence", "interpretation", "preservation", "ambiguities")},
        "required": ["evidence", "interpretation", "preservation", "ambiguities"]},
}
OPERATION_HELP = {
    "trim_whitespace": "trim_whitespace: {}",
    "normalize_values": "normalize_values: mapping/case/strip_whitespace",
    "convert_data_types": "convert_data_types: casts already-clean values to target_type; strips no symbols",
    "clean_numeric_string": "clean_numeric_string: parses numbers from text ($, commas, k/m/b, number words, (500))",
    "handle_missing_values": "handle_missing_values: strategy fill_median/fill_mean/fill_mode/fill_constant (+fill_value); marks <column>_imputed",
    "parse_datetime": "parse_datetime: date_formats (strftime codes like %Y-%m-%d) or dayfirst",
    "standardize_missing": "standardize_missing: extra markers to null",
    "remove_duplicates": "remove_duplicates: columns=key, all columns=exact rows; optional keep; no checks needed (removal is verified)",
    "handle_outliers": "handle_outliers: action cap/set_missing, method iqr (k) or bounds (lower/upper)",
}
FORMATTING = ("trim_whitespace", "normalize_values", "standardize_missing")
# Each focused task sees only the operations its category may use; other categories see the whole catalog.
CATEGORY_OPERATIONS = {
    "formatting": FORMATTING,
    "types": FORMATTING + ("convert_data_types", "clean_numeric_string", "parse_datetime"),
    "missing": ("standardize_missing", "handle_missing_values"),
    "duplicates": ("remove_duplicates",),
    "outliers": ("handle_outliers",),
}


def task_operations(state, task):
    """Builtins the active task may use; type tasks only see parsers for their target type."""
    allowed = CATEGORY_OPERATIONS.get(task["category"]) if task else None
    if not allowed or task["category"] != "types":
        return allowed
    targets = {canonical_type(state.required_targets[c]) for c in task["columns"] if c in state.required_targets}
    if not targets:
        return allowed
    numeric = targets <= {"numeric", "float", "integer"}
    dates = targets <= {"datetime"}
    return tuple(op for op in allowed if (op != "clean_numeric_string" or numeric) and (op != "parse_datetime" or dates))


def whitespace_only(task):
    """A finding about spaces alone permits nothing else to change; a run once lowercased every region to fix spaces."""
    return bool(task and task["category"] == "formatting" and task["evidence"]
                and all("whitespace" in str(e.get("issue_id", "")).lower() for e in task["evidence"]))


def builtin_tool(operations=CATALOG):
    parameters = {"type": "object", "additionalProperties": False,
        "properties": {k: v for operation in operations for k, v in METHOD_SCHEMAS[operation]["properties"].items()
                       if k not in {"column", "columns", "subset"}}}
    return tool("test_builtin", "Test ONLY a catalog operation on a copy. Python code is not accepted. "
         + "; ".join(OPERATION_HELP[operation] for operation in operations) + ". "
         "Passing trials are applied automatically. If one fails, change parameters or operation, or use test_generated.",
         {**METHOD_FIELDS, "operation": {"type": "string", "enum": list(operations)}, "parameters": parameters},
         ["hypothesis", "columns", "operation"])  # parameters default to {}; trim_whitespace takes none


SCHEMAS_LIST = [
    tool("inspect_data", "Read working data. duplicates checks full rows or keys given by column/subset. reason explains the remaining question and why this view helps. Column views require column. distribution gives full-column numeric stats; extremes smallest/largest; filtered matching examples; relationships compares column with related_column. Repeats reuse evidence and do not advance a task.",
         {"reason": STRING, "question": STRING, "expected_evidence": STRING,
          "view": {"type": "string", "enum": ["schema", "column", "patterns", "values", "duplicates", "distribution", "extremes", "filtered", "relationships"]},
          "related_column": STRING, "subset": STRINGS,
          "filter": {"type": "string", "enum": ["missing", "non_numeric", "negative", "zero", "positive", "iqr_outliers", "less_than", "greater_than"]},
          "threshold": {"type": "number"},
          "column": STRING, "offset": {"type": "integer", "minimum": 0},
          "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, ["reason", "view"]),
    builtin_tool(),
    tool("test_generated", "Explicit method for YOUR generated Python code. Supply complete transform(df), returning a DataFrame; checks are optional (default: columns keep their type). "
         "No operation or parameters. Docker unavailability stops the run; no builtin fallback. "
         "Passing trials are automatically applied after full-data validation.",
         {**METHOD_FIELDS, "code": {"type": "string", "minLength": 1, "maxLength": 8000}},
         ["hypothesis", "columns", "code"]),
    tool("apply_candidate", "Apply a passing candidate after full-data checks. Assessment refers to measured trial results.",
         {"candidate_id": STRING, "assessment": STRING}, ["candidate_id", "assessment"]),
    tool("flag_for_review", "Set ambiguous columns aside for human review. They cannot change again this run.",
         {"columns": STRINGS, "reason": STRING}, ["columns", "reason"]),
    tool("complete_task", "Assess only the active advisory task after inspection. Measured tasks advance through dataset checks or flag_for_review.",
         {"task_id": STRING, "disposition": {"type": "string", "enum": ["reviewed", "needs_review"]},
          "reason": STRING}, ["task_id", "disposition", "reason"]),
    tool("finish", "Finish and independently validate the persisted dataset. When task=null call this, not complete_task.",
         {"summary": STRING, "unresolved": {"type": "array", "items": STRING}}, ["summary"]),
]
SCHEMA = {t["function"]["name"]: t["function"]["parameters"] for t in SCHEMAS_LIST}
TEST_TOOLS = {"test_builtin", "test_generated"}
VALIDATORS = {name: Draft202012Validator(schema) for name, schema in SCHEMA.items()}


def available_tools(state):
    from .cleaning_tasks import active
    task = active(state)
    if not task:
        return [t for t in SCHEMAS_LIST if not (state.sandbox_error and t["function"]["name"] == "test_generated")]
    tools = []
    for t in SCHEMAS_LIST:
        if t["function"]["name"] == "test_generated" and state.sandbox_error:
            continue
        if t["function"]["name"] == "test_builtin":
            if task.get("generated_required"):
                continue
            if task["category"] in CATEGORY_OPERATIONS:
                t = builtin_tool(task_operations(state, task))
        tools.append(t)
    return tools


def fingerprint(arguments):
    return digest(json.dumps({"op": arguments.get("operation"), "columns": sorted(arguments["columns"]),
        "parameters": arguments.get("parameters", {}), "code": (arguments.get("code") or "").strip(),
        "checks": sorted(json.dumps(c, sort_keys=True) for c in arguments.get("checks", [])),
        "verify_numeric_values": arguments.get("verify_numeric_values", True)}, sort_keys=True).encode())


def validate_request(name, arguments):
    """Validate canonical public arguments before duplicate lookup or execution."""
    if name not in SCHEMA:
        return {"success": False, "error_kind": "invalid_tool_arguments", "error": f"Unknown tool: {name}"}
    if name == "test_builtin" and isinstance(arguments, dict) and isinstance(arguments.get("parameters"), dict) and "columns" in arguments["parameters"]:
        return {"success": False, "error_kind": "invalid_tool_arguments",
                "error": "Conflicting or invalid columns: declare target columns once at the top level; parameters contains method options only."}
    errors = list(VALIDATORS[name].iter_errors(arguments))
    if errors:
        return {"success": False, "error_kind": "invalid_tool_arguments", "error": "; ".join(e.message for e in errors)}
    return None


def dispatch(executor, name, arguments):
    """Execute a validated request; public validation belongs to ToolExecutor."""
    from .cleaning_tasks import check_scope, complete
    if executor.state.focused_cleaning:
        try:
            check_scope(executor.state, name, arguments)
        except ValueError as exc:
            return {"success": False, "error_kind": "invalid_tool_arguments", "error": str(exc)}
    if name == "test_generated" and not executor.state.sandbox_checked:
        from .experiments import runtime_status
        runtime = runtime_status()
        if not runtime.get("available"):
            return {"success": False, "tested": False, "error_kind": "sandbox_unavailable",
                    "error": "Docker sandbox unavailable: " + runtime.get("error", "Unknown runtime error"),
                    "setup": runtime.get("setup"), "transient": runtime.get("transient", False)}
        executor.state.sandbox_checked = True
    if name == "complete_task":
        return complete(executor, arguments)
    if name == "finish":
        return executor._finish(arguments)
    return {"inspect_data": inspect_data, "test_builtin": test_candidate, "test_generated": test_candidate, "apply_candidate": apply_candidate,
            "flag_for_review": flag_for_review}[name](executor, arguments)


def inspect_data(executor, arguments):
    from .inspection import inspection_query
    from .investigation import inspect
    query = inspection_query(arguments)
    columns = query.get("subset", []) + [query[k] for k in ("column", "related_column") if k in query]
    unknown = set(columns) - set(executor.state.current_ref.columns)
    if unknown:
        raise ValueError(f"Unknown columns: {sorted(unknown)}")
    return inspect(executor, {**arguments, **query}, read_inspection)


def read_inspection(executor, arguments):
    if arguments["view"] in {"distribution", "extremes", "filtered", "relationships"}:
        from .inspection import investigate_column
        return investigate_column(executor.state.current_ref, arguments, executor.state.manager)
    if arguments["view"] == "values":
        from .inspection import inspect_values
        return inspect_values(executor.state.current_ref, arguments["column"], arguments.get("offset", 0),
                              arguments.get("limit", 50), executor.state.manager)
    return {"schema": executor._inspect_schema, "column": executor._inspect_column,
            "patterns": executor._check_value_patterns, "duplicates": executor._inspect_duplicates}[arguments["view"]](arguments)


def flag_for_review(executor, arguments):
    frame = executor.state.manager.load(executor.state.current_ref)
    unknown = set(arguments["columns"]) - set(frame.columns)
    if unknown:
        raise ValueError(f"Unknown columns: {sorted(unknown)}")
    executor.state.flagged.update({c: arguments["reason"] for c in arguments["columns"]})
    executor.state.validation = None
    return {"success": True, "message": "Columns flagged for review; remaining checks do not certify these columns.",
            "flagged": dict(executor.state.flagged)}


def builtin_parameters(operation, parameters, columns):
    if operation not in CATALOG:
        raise ValueError("Choose a catalog operation or provide generated code")
    parameters = dict(parameters)

    if "target_type" in parameters:
        parameters["target_type"] = canonical_type(parameters["target_type"])
    if operation == "clean_numeric_string" and parameters.get("target_type") in {"float", "numeric"}:
        # It always produces numbers; models naturally state the target, which is redundant, not wrong.
        parameters.pop("target_type")
    if operation == "trim_whitespace" and parameters.get("strip_whitespace") is True:
        # Stripping is all it does; normalize_values' option shares the tool schema, and correction repeated it.
        parameters.pop("strip_whitespace")
    if operation == "handle_missing_values" and parameters.get("strategy") in {"drop_rows", "drop_columns"}:
        raise ValueError("Structural changes require host approval; flag_for_review instead")
    declared = parameters.get("columns") or ([parameters["column"]] if "column" in parameters else columns)
    if set(declared) != set(columns):
        raise ValueError("Parameters must target exactly the declared columns")
    schema = {**METHOD_SCHEMAS[operation], "properties": dict(METHOD_SCHEMAS[operation]["properties"])}
    if operation in PER_COLUMN and "column" not in parameters:
        parameters["columns"] = columns
        schema["properties"]["columns"] = STRINGS
        schema["required"] = ["columns" if key == "column" else key for key in schema["required"]]
    elif operation == "remove_duplicates":
        parameters["subset"] = columns
    elif operation not in PER_COLUMN:
        parameters.setdefault("columns", columns)
    errors = list(Draft202012Validator(schema).iter_errors(parameters))
    if errors:
        allowed = [k for k in METHOD_SCHEMAS[operation]["properties"] if k not in {"column", "columns", "subset"}]
        raise ValueError("Invalid builtin parameters: " + "; ".join(e.message for e in errors)
                         + f". {operation} accepts only: {', '.join(allowed) or 'no parameters ({})'}")
    if operation == "handle_missing_values" and parameters.get("strategy") == "fill_constant" and parameters.get("fill_value") is None:
        raise ValueError("fill_constant requires an explicit non-null fill_value")
    if operation == "handle_outliers" and parameters["method"] == "bounds" and "lower" not in parameters and "upper" not in parameters:
        raise ValueError("handle_outliers method=bounds requires lower and/or upper")
    return parameters


def current_kind(series):
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_integer_dtype(series):
        return "integer"
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    return "string"


def test_candidate(executor, arguments):
    state = executor.state
    if time.monotonic() >= state.deadline:
        raise ValueError("Run time budget expired")
    frame = state.manager.load(state.current_ref)
    columns = arguments["columns"]
    if set(columns) - set(frame.columns):
        raise ValueError(f"Unknown columns: {sorted(set(columns) - set(frame.columns))}")
    if set(columns) & set(state.flagged):
        raise ValueError("Those columns are flagged for human review")
    generated = bool(arguments.get("code"))
    arguments = dict(arguments)
    if not generated:
        arguments["parameters"] = builtin_parameters(arguments.get("operation"), arguments.get("parameters", {}), columns)
        if arguments["operation"] == "remove_duplicates" and set(columns) == set(frame.columns):
            arguments["parameters"]["subset"] = None  # exact full-row duplicates
    removes_rows = arguments.get("operation") in ROW_REMOVAL
    checks = list(arguments.get("checks", []))
    if any(check["column"] not in columns for check in checks):
        raise ValueError("Checks must refer to selected columns")
    from .cleaning_tasks import active
    task = active(state) if state.focused_cleaning else None
    arguments["verify_numeric_values"] = not removes_rows and (task["category"] in {"types", "missing"} if task else
        generated or arguments.get("operation") in {"convert_data_types", "clean_numeric_string", "handle_missing_values"})
    if task and task["category"] != "missing" and not removes_rows:
        checks += [{"column": c, "kind": "preserve_missing"} for c in columns]
    if whitespace_only(task):
        checks += [{"column": c, "kind": "whitespace_only"} for c in columns]
    if generated or task:
        checks += [{"column": c, "kind": CHECK_KIND.get(canonical_type(state.required_targets[c]), canonical_type(state.required_targets[c]))}
                   for c in columns if c in state.required_targets and (not task or task["category"] in {"types", "missing"})]
    if generated:
        checks += [{"column": c, "kind": "no_missing"} for c in columns if c in state.required_missing
                   and (not task or task["category"] == "missing")]
        if not arguments.get("checks") and not (task and task["category"] == "types"):
            # Omitted outcomes default to each column keeping its current type; type tasks rely on their targets.
            checks += [{"column": c, "kind": current_kind(frame[c])} for c in columns
                       if not any(k["column"] == c and k["kind"] in CHECK_KIND.values() for k in checks)]
    arguments["checks"] = [dict(items) for items in dict.fromkeys(tuple(sorted(c.items())) for c in checks)]
    key = fingerprint(arguments)
    if state.failures.get(key, 0) >= 3:
        raise ValueError("This method failed three times. Change the method, flag_for_review, or finish.")
    for existing_id, existing in state.method_candidates.items():
        if existing["key"] != key or existing["base_version"] != state.current_ref.version:
            continue
        applied = any(event["tool"] == "apply_candidate" and event["arguments"].get("candidate_id") == existing_id
                      and event["result"].get("success") for event in state.events)
        status = "failed" if not existing["tested"] else "already_applied" if applied else "passed"
        advice = {
            "failed": "This candidate failed. Do not apply or repeat it. Inspect the unparsed values, revise the method, or flag genuine ambiguity for review.",
            "passed": "This candidate passed its trial but has not been applied successfully. Use its recorded results to assess application; do not retest identical arguments.",
            "already_applied": "This candidate was already applied successfully. Do not apply or repeat it; address the remaining obligations.",
        }[status]
        return {"success": False, "error_kind": "duplicate_method", "candidate_id": existing_id,
                "candidate_status": status, "tested": existing["tested"],
                "error": "Already tested on this version. " + advice,
                "failure_summary": existing.get("failure_summary")}
    if generated:
        result = experiment(state, {**arguments, "rationale": arguments["hypothesis"],
            "expected_effect": "Declared checks and selected-column obligations must pass"})
        internal_id = result["candidate_id"]
        ok = result["tested"]
    else:
        out = run_builtin(frame.copy(deep=True), arguments["operation"], arguments["parameters"])
        effect = builtin_effect(frame, out.df, arguments) if out.success and out.df is not None else None
        ok = bool(effect and effect["accepted"])
        result = {"success": ok, "tested": ok, "effect": effect, "error": out.error,
                  "message": "Full-data copy tested; working data unchanged."}
        internal_id = None
    candidate_id = f"c{len(state.method_candidates) + 1}"
    if not ok:
        result["failure_summary"] = failure_summary(result)
        result["error"] = result["failure_summary"]["reason"]
        result["message"] = "Candidate rejected; working data unchanged. " + result["failure_summary"]["next_action"]
    state.method_candidates[candidate_id] = {**arguments, "key": key, "tested": ok,
        "base_version": state.current_ref.version, "kind": "generated" if generated else "builtin",
        "experiment_id": internal_id, "dataset_hash": digest(Path(state.current_ref.path).read_bytes()),
        "failure_summary": result.get("failure_summary")}
    if not ok:
        state.failures[key] = state.failures.get(key, 0) + 1
    return {**result, "candidate_id": candidate_id, "hypothesis": arguments["hypothesis"]}


def builtin_effect(before, after, candidate):
    effect = assess_candidate(before, after, candidate["operation"], candidate["columns"], candidate["parameters"])
    expected = assess_method(before, after, candidate["columns"], candidate.get("checks", []),
        verify_numeric_values=candidate.get("verify_numeric_values", True))
    effect["rules"].extend(r for r in expected["rules"] if r["rule_name"].startswith("expected:"))
    effect["accepted"] = all(r["passed"] for r in effect["rules"])
    return effect


def apply_candidate(executor, arguments):
    state = executor.state
    if time.monotonic() >= state.deadline:
        raise ValueError("Run time budget expired before candidate application")
    candidate = state.method_candidates.get(arguments["candidate_id"])
    if candidate is None:
        raise ValueError("Unknown candidate_id; use the ID returned by test_builtin or test_generated")
    if not candidate["tested"]:
        raise ValueError("Trial failed; revise and test again")
    if candidate["base_version"] != state.current_ref.version:
        raise ValueError("Data changed since testing; test again")
    # Version files remain writable. These host-only checks preserve integrity
    # without adding model fields, tools or turns.
    if candidate["dataset_hash"] != digest(Path(state.current_ref.path).read_bytes()) or candidate["key"] != fingerprint(candidate):
        raise ValueError("Tested data or method changed; test again")
    if set(candidate["columns"]) & set(state.flagged):
        raise ValueError("Those columns are flagged for human review")
    state.decisions.append({**arguments, "version": state.current_ref.version})
    if candidate["kind"] == "generated":
        result = executor._apply_experimental_method({"candidate_id": candidate["experiment_id"]})
    else:
        def full(frame, **parameters):
            result = run_builtin(frame, candidate["operation"], parameters)
            if result.success and result.df is not None:
                effect = builtin_effect(frame, result.df, candidate)
                if not effect["accepted"]:
                    return cleaning.CleaningResult(False, error="Full-data checks failed", details={"full_data_effect": effect})
            return result
        result = executor._clean(candidate["operation"], full,
            {**candidate["parameters"], "rationale": candidate["hypothesis"]}, candidate["columns"])
    if not result["success"] and not result.get("approval_required"):
        state.failures[candidate["key"]] = state.failures.get(candidate["key"], 0) + 1
    return {**result, "candidate_id": arguments["candidate_id"], "remaining": executor.progress()}


def run_builtin(frame, operation, parameters):
    parameters = dict(parameters)
    if operation == "handle_missing_values" and parameters.get("strategy") in {"fill_mean", "fill_median"}:
        invalid = [c for c in parameters["columns"] if not cleaning.pd.api.types.is_numeric_dtype(frame[c]) or cleaning.pd.api.types.is_bool_dtype(frame[c])]
        if invalid:
            raise ValueError(f"{parameters['strategy']} requires numeric columns; inspect and convert first: {invalid}")
    if operation in PER_COLUMN and "columns" in parameters:
        columns = parameters.pop("columns")
        current, affected = frame.copy(deep=True), 0
        for column in columns:
            result = getattr(cleaning, operation)(current, column=column, **parameters)
            if not result.success:
                result.error = f"{operation} failed on column {column}: {result.error or result.message}"
                return result
            current, affected = result.df, affected + result.affected_rows
        return cleaning.CleaningResult(True, df=current, affected_rows=affected, message=f"Applied {operation} to {len(columns)} columns")
    return getattr(cleaning, operation)(frame, **parameters)
