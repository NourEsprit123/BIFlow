"""Inspect → test on a copy → apply → finish. No stage machine or issue ledger."""
from __future__ import annotations

import json
import time
from pathlib import Path
from jsonschema import Draft202012Validator
from . import cleaning
from .contracts import canonical_type, model_arguments
from .effects import assess_candidate
from .experiments import assess_method, digest, experiment
from .method_catalog import SCHEMAS as METHOD_SCHEMAS

CATALOG = {
    "trim_whitespace": "Remove surrounding whitespace.",
    "normalize_values": "Edit text spelling/case; does not convert types.",
    "convert_data_types": "Convert selected columns; boolean accepts Yes/No, True/False and 1/0.",
    "clean_numeric_string": "Parse currency and abbreviated numbers.",
    "handle_missing_values": "Fill selected columns using a justified strategy; mean/median need numeric data.",
}
PARAMETERS = {"trim_whitespace": {}, "normalize_values": {"mapping": {"old": "new"}},
    "convert_data_types": {"target_type": "boolean", "errors": "raise"},
    "clean_numeric_string": {"errors": "raise"}, "handle_missing_values": {"strategy": "fill_median"}}
OPTIONS = {
    "normalize_values": {"case": ["lower", "upper", "title"], "strip_whitespace": "boolean"},
    "convert_data_types": {"target_type": ["numeric", "float", "integer", "boolean", "datetime", "string"],
        "errors": ["raise", "coerce", "ignore"], "date_format": "optional strptime format"},
    "clean_numeric_string": {"errors": ["raise", "coerce", "ignore"]},
    "handle_missing_values": {"strategy": ["fill_constant", "fill_mean", "fill_median", "fill_mode"],
        "fill_value": "required for fill_constant"}}
CHECK_KIND = {"numeric": "numeric", "float": "numeric", "integer": "integer", "boolean": "boolean",
              "datetime": "datetime", "string": "string"}
STRING = {"type": "string", "minLength": 1}
STRINGS = {"type": "array", "items": STRING, "minItems": 1, "uniqueItems": True}
CHECKS = {"type": "array", "minItems": 1, "items": {"type": "object", "additionalProperties": False,
    "properties": {"column": STRING, "kind": {"type": "string", "enum": ["no_missing", "unique", "non_negative",
        "numeric", "integer", "boolean", "datetime", "string"]}}, "required": ["column", "kind"]}}


def tool(name, description, properties, required):
    return {"type": "function", "function": {"name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required, "additionalProperties": False}}}


SCHEMAS_LIST = [
    tool("inspect_data", "Read working data. Views column/patterns require column.",
         {"view": {"type": "string", "enum": ["schema", "column", "patterns", "duplicates"]}, "column": STRING}, ["view"]),
    tool("test_method", "Test a builtin operation/parameters or generated transform(df) on a copy. Never commits data.",
         {"hypothesis": STRING, "columns": STRINGS, "operation": {"type": "string", "enum": list(CATALOG)},
          "parameters": {"type": "object"}, "code": {"type": "string", "minLength": 1, "maxLength": 8000},
          "checks": CHECKS}, ["hypothesis", "columns"]),
    tool("apply_candidate", "Apply a passing candidate after full-data checks. Assessment must refer to measured trial results.",
         {"candidate_id": STRING, "assessment": STRING}, ["candidate_id", "assessment"]),
    tool("flag_for_review", "Set ambiguous columns aside for human review. They cannot be changed again in this run.",
         {"columns": STRINGS, "reason": STRING}, ["columns", "reason"]),
    tool("finish", "Finish; BIFlow validates outstanding obligations and reports exceptions separately.",
         {"summary": STRING, "unresolved": {"type": "array", "items": STRING}}, ["summary"])]
SCHEMA = {t["function"]["name"]: t["function"]["parameters"] for t in SCHEMAS_LIST}
NAMES = set(SCHEMA) - {"finish"}


def fingerprint(arguments):
    return digest(json.dumps({"op": arguments.get("operation"), "columns": sorted(arguments["columns"]),
        "parameters": arguments.get("parameters", {}), "code": (arguments.get("code") or "").strip(),
        "checks": sorted(json.dumps(c, sort_keys=True) for c in arguments.get("checks", []))}, sort_keys=True).encode())


def dispatch(executor, name, arguments):
    arguments = model_arguments(name, arguments)
    errors = list(Draft202012Validator(SCHEMA[name]).iter_errors(arguments))
    if errors:
        return {"success": False, "error_kind": "invalid_tool_arguments", "error": "; ".join(e.message for e in errors)}
    if name == "finish":
        return executor._finish(arguments)
    return {"inspect_data": inspect_data, "test_method": test_method, "apply_candidate": apply_candidate,
            "flag_for_review": flag_for_review}[name](executor, arguments)


def inspect_data(executor, arguments):
    if arguments["view"] in {"column", "patterns"} and "column" not in arguments:
        raise ValueError(f"view={arguments['view']} requires column")
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
    if operation == "handle_missing_values" and parameters.get("strategy") in {"drop_rows", "drop_columns"}:
        raise ValueError("Structural changes require host approval; flag_for_review instead")
    declared = parameters.get("columns") or ([parameters["column"]] if "column" in parameters else columns)
    if set(declared) != set(columns):
        raise ValueError("Parameters must target exactly the declared columns")
    schema = json.loads(json.dumps(METHOD_SCHEMAS[operation]))
    if operation in {"convert_data_types", "clean_numeric_string", "normalize_values"} and "column" not in parameters:
        parameters["columns"] = columns
        schema["properties"]["columns"] = STRINGS
        schema["required"] = ["columns" if key == "column" else key for key in schema["required"]]
    elif operation in {"trim_whitespace", "handle_missing_values"}:
        parameters.setdefault("columns", columns)
    errors = list(Draft202012Validator(schema).iter_errors(parameters))
    if errors:
        raise ValueError("Invalid builtin parameters: " + "; ".join(e.message for e in errors))
    if operation == "handle_missing_values" and parameters.get("strategy") == "fill_constant" and parameters.get("fill_value") is None:
        raise ValueError("fill_constant requires an explicit non-null fill_value")
    return parameters


def test_method(executor, arguments):
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
    if generated and arguments.get("operation"):
        raise ValueError("Provide either operation/parameters or code, not both")
    if generated and not arguments.get("checks"):
        raise ValueError("Generated code requires at least one outcome check")
    arguments = dict(arguments)
    if not generated:
        arguments["parameters"] = builtin_parameters(arguments.get("operation"), arguments.get("parameters", {}), columns)
    checks = list(arguments.get("checks", []))
    if any(check["column"] not in columns for check in checks):
        raise ValueError("Checks must refer to selected columns")
    if generated:
        checks += [{"column": c, "kind": CHECK_KIND.get(canonical_type(state.required_targets[c]), canonical_type(state.required_targets[c]))}
                   for c in columns if c in state.required_targets]
        checks += [{"column": c, "kind": "no_missing"} for c in columns if c in state.required_missing]
    arguments["checks"] = [dict(items) for items in dict.fromkeys(tuple(sorted(c.items())) for c in checks)]
    key = fingerprint(arguments)
    if state.failures.get(key, 0) >= 3:
        raise ValueError("This method failed three times. Change the method, flag_for_review, or finish.")
    if any(c["key"] == key and c["base_version"] == state.current_ref.version for c in state.method_candidates.values()):
        raise ValueError("Already tested on this version. Apply the passing candidate or change the method.")
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
    state.method_candidates[candidate_id] = {**arguments, "key": key, "tested": ok,
        "base_version": state.current_ref.version, "kind": "generated" if generated else "builtin",
        "experiment_id": internal_id, "dataset_hash": digest(Path(state.current_ref.path).read_bytes())}
    if not ok:
        state.failures[key] = state.failures.get(key, 0) + 1
    return {**result, "candidate_id": candidate_id, "hypothesis": arguments["hypothesis"]}


def builtin_effect(before, after, candidate):
    effect = assess_candidate(before, after, candidate["operation"], candidate["columns"], candidate["parameters"])
    expected = assess_method(before, after, candidate["columns"], candidate.get("checks", []))
    effect["rules"].extend(r for r in expected["rules"] if r["rule_name"].startswith("expected:"))
    effect["accepted"] = all(r["passed"] for r in effect["rules"])
    return effect


def apply_candidate(executor, arguments):
    state = executor.state
    candidate = state.method_candidates.get(arguments["candidate_id"])
    if candidate is None:
        raise ValueError("Unknown candidate_id; use the ID returned by test_method")
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
    if operation in {"convert_data_types", "clean_numeric_string", "normalize_values"} and "columns" in parameters:
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
