"""Small model-facing interface for evidence-led cleaning experiments.

Trusted methods run on copies. Generated code always uses the Docker runner.
Neither a successful trial nor the model's review can commit working data.
"""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from jsonschema import Draft202012Validator

from . import cleaning
from .contracts import canonical_type
from .effects import assess_candidate, present, target_matches
from .experiments import assess_method, digest, experiment

CATALOG = {
    "trim_whitespace": "Remove surrounding whitespace in selected text columns.",
    "normalize_values": "Edit text spelling/case using explicit mappings; does not change types.",
    "convert_data_types": "Convert one column; boolean accepts Yes/No, True/False and 1/0.",
    "clean_numeric_string": "Parse currency and abbreviated numeric strings.",
    "handle_missing_values": "Fill explicit columns with a justified strategy; median/mean require numeric data.",
}
PARAMETERS = {
    "trim_whitespace": {"columns": ["column_name"]},
    "normalize_values": {"column": "column_name", "mapping": {"old": "new"}, "case": "lower|upper|title", "strip_whitespace": True},
    "convert_data_types": {"column": "column_name", "target_type": "numeric|float|integer|boolean|datetime|string", "errors": "raise|coerce|ignore", "date_format": "optional"},
    "clean_numeric_string": {"column": "column_name", "errors": "raise|coerce|ignore"},
    "handle_missing_values": {"columns": ["column_name"], "strategy": "fill_constant|fill_mean|fill_median|fill_mode", "fill_value": "only for fill_constant"},
}


def tool(name, description, properties, required):
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties,
                           "required": required, "additionalProperties": False}}}


STRING = {"type": "string", "minLength": 1}
STRINGS = {"type": "array", "items": STRING}
CHECKS = {"type": "array", "minItems": 1, "items": {
    "type": "object", "properties": {"column": STRING, "kind": {"type": "string", "enum": [
        "no_missing", "unique", "non_negative", "numeric", "integer", "boolean", "datetime", "string"]}},
    "required": ["column", "kind"], "additionalProperties": False}}

WORKFLOW_SCHEMAS = [
    tool("inspect_data", "Read evidence from the current working data; never changes data.",
         {"view": {"enum": ["schema", "column", "patterns", "duplicates"]}, "column": STRING}, ["view"]),
    tool("test_method", "Propose a hypothesis and test a builtin or generated method on copies. Does not apply changes.", {
        "issue_ids": {**STRINGS, "minItems": 1}, "hypothesis": STRING, "assumptions": STRINGS,
        "rationale": STRING, "expected_effect": STRING, "evidence_ids": {**STRINGS, "minItems": 1},
        "columns": {**STRINGS, "minItems": 1}, "kind": {"enum": ["builtin", "generated"]},
        "operation": {"enum": list(CATALOG)}, "parameters": {"type": "object"},
        "code": {"type": "string", "maxLength": 8000}, "checks": CHECKS,
    }, ["issue_ids", "hypothesis", "assumptions", "rationale", "expected_effect", "evidence_ids", "columns", "kind", "checks"]),
    tool("review_candidate", "Evaluate actual trial results. Accept only a passing candidate, or explain a concrete revision.", {
        "candidate_id": STRING, "decision": {"enum": ["accept", "revise"]},
        "assessment": STRING, "next_change": {"type": "string"}}, ["candidate_id", "decision", "assessment"]),
    tool("apply_candidate", "Apply an accepted, tested, unchanged candidate after full-data checks.",
         {"candidate_id": STRING}, ["candidate_id"]),
    tool("request_review", "Record an ambiguous business decision or structural change requiring human review.",
         {"issue_ids": {**STRINGS, "minItems": 1}, "reason": STRING}, ["issue_ids", "reason"]),
    tool("finish", "Finish; the application independently validates the actual working data.",
         {"summary": STRING, "unresolved": STRINGS}, ["summary"]),
]
NAMES = {t["function"]["name"] for t in WORKFLOW_SCHEMAS} - {"finish"}


def initialize(state, report):
    for column, profile in report.column_profiles.items():
        state.evidence.setdefault(f"profile:{column}", {
            "source": "profiling observation", "column": column,
            "dtype": profile.dtype, "missing_count": profile.missing_count,
            "suggested_target": profile.etl_cast_to})
    for column, target in state.required_targets.items():
        state.issues[f"type:{column}"] = {"column": column, "kind": "type",
            "target": canonical_type(target), "evidence_ids": [f"profile:{column}"],
            "status": "pending", "failed_trials": 0}
    for column in state.required_missing:
        state.issues[f"missing:{column}"] = {"column": column, "kind": "missing",
            "evidence_ids": [f"profile:{column}"], "status": "pending", "failed_trials": 0}
    for column, profile in report.column_profiles.items():
        for number, issue in enumerate(profile.issues):
            state.issues[f"finding:{column}:{number}"] = {"column": column, "kind": "finding",
                "description": issue.description, "evidence_ids": [f"profile:{column}:{issue.issue_id}:{number}"],
                "status": "pending", "failed_trials": 0}
    # ETL hints can refer to columns absent from column_profiles.
    for column in state.required_targets:
        state.evidence.setdefault(f"profile:{column}", {"source": "profiling type hint", "column": column,
                                  "suggested_target": state.required_targets[column]})


def refresh(state):
    frame = state.manager.load(state.current_ref)
    for issue in state.issues.values():
        column = issue["column"]
        if issue["kind"] in {"type", "missing"} and issue["status"] != "awaiting_review":
            complete = column in frame and (target_matches(frame[column], issue["target"])
                if issue["kind"] == "type" else present(frame[column]).all())
            issue["status"] = "resolved" if complete else "pending"


def stage_context(state):
    refresh(state)
    prompt = (Path(__file__).resolve().parents[1] / "agents/prompts/cleaning_stages" / f"{state.workflow_stage}.md").read_text(encoding="utf-8")
    candidates = {key: {"tested": c["tested"], "kind": c["kind"], "issue_ids": c["issue_ids"],
                        "review": c.get("review"), "base_version": c["base_version"]}
                  for key, c in state.method_candidates.items()}
    catalog = "\nBuiltin method catalog and parameter shapes (replace example placeholders; optional parameters may be omitted):\n" + json.dumps({k: {"purpose": CATALOG[k], "parameters": PARAMETERS[k]} for k in CATALOG}) if state.workflow_stage in {"understand", "propose", "revise"} else ""
    return (prompt + "\nIssue ledger (profiling recommendations require critical assessment):\n" + json.dumps(state.issues)
            + "\nCandidate ledger:\n" + json.dumps(candidates) + catalog)


def schemas(state):
    allowed = {
        "understand": {"inspect_data", "test_method", "request_review", "finish"},
        "propose": {"inspect_data", "test_method", "request_review", "finish"},
        "evaluate": {"inspect_data", "review_candidate", "request_review", "finish"},
        "revise": {"inspect_data", "test_method", "review_candidate", "request_review", "finish"},
        "apply": {"inspect_data", "apply_candidate", "review_candidate", "request_review", "finish"},
        "conclude": {"finish", "request_review"},
    }[state.workflow_stage]
    return [t for t in WORKFLOW_SCHEMAS if t["function"]["name"] in allowed]


def revision_feedback(state, name, args, result):
    """Return explicit measured failure feedback to the next model request."""
    failure = not result.get("success", True) or result.get("no_op")
    if not failure or result.get("approval_required"):
        return None
    state.workflow_stage = "revise"
    details = result.get("details") if isinstance(result.get("details"), dict) else {}
    effect = result.get("effect") or details.get("full_data_effect") or {}
    failed_rules = effect.get("rules", []) or result.get("rules", []) or (result.get("validation") or {}).get("rules", [])
    return {
        "stage": "revise", "tool": name, "arguments": args,
        "error": result.get("error") or result.get("message") or "Candidate checks failed",
        "failed_checks": [r for r in failed_rules if not r["passed"]],
        "trials": [{"partition": t["partition"], "error": t.get("error"),
                    "failed_checks": [r for r in (t.get("effect") or {}).get("rules", []) if not r["passed"]]}
                   for t in result.get("trials", []) if not t.get("success")],
        "prompt": "The last attempt did not establish a successful repair. Distinguish invalid arguments, incompatible data, failed expectations, and unavailable runtime. Explain a changed hypothesis or concrete method revision using this evidence. Inspect unresolved values if necessary. If builtin semantics cannot address the data, test a generated transform(df) in Docker. Do not repeat the unchanged attempt or invent business meaning. Request review when ambiguous; report runtime failures honestly.",
    }


def dispatch(executor, name, args):
    state = executor.state
    schema = next(t["function"]["parameters"] for t in WORKFLOW_SCHEMAS if t["function"]["name"] == name)
    errors = list(Draft202012Validator(schema).iter_errors(args))
    if errors:
        raise ValueError("; ".join(e.message for e in errors))
    if name == "inspect_data":
        handlers = {"schema": executor._inspect_schema, "column": executor._inspect_column,
                    "patterns": executor._check_value_patterns, "duplicates": executor._inspect_duplicates}
        result = handlers[args["view"]](args)
        state.workflow_stage = "propose" if state.workflow_stage == "understand" else state.workflow_stage
        return result
    if name == "test_method":
        return test_method(executor, args)
    if name in {"review_candidate", "apply_candidate"}:
        candidate = state.method_candidates.get(args["candidate_id"])
        if candidate is None:
            raise ValueError("Unknown candidate ID; test_method must produce the candidate first")
        if name == "review_candidate":
            if args["decision"] == "accept" and not candidate["tested"]:
                raise ValueError("Failed trials cannot be accepted. Revise using measured failures.")
            if args["decision"] == "revise" and not args.get("next_change", "").strip():
                raise ValueError("A revision must state a concrete next_change")
            candidate["review"] = dict(args)
            state.decisions.append({**args, "stage": "evaluate"})
            state.workflow_stage = "apply" if args["decision"] == "accept" else "revise"
            return {"success": True, "candidate_id": args["candidate_id"], "decision": args["decision"]}
        return apply_candidate(executor, candidate)
    for key in args["issue_ids"]:
        if key not in state.issues:
            raise ValueError(f"Unknown issue ID: {key}")
    for key in args["issue_ids"]:
        state.issues[key]["status"] = "awaiting_review"
    reason = f"Review required for {args['issue_ids']}: {args['reason']}"
    state.pending_approvals.append(reason)
    state.decisions.append({"stage": "review", **args})
    state.workflow_stage = "understand"
    return {"success": True, "approval_required": True, "message": reason}


def test_method(executor, args):
    state = executor.state
    for key in args["issue_ids"]:
        if key not in state.issues:
            raise ValueError(f"Unknown issue ID: {key}")
        if state.issues[key]["status"] == "awaiting_review":
            raise ValueError("This issue is awaiting human review; do not experiment around that decision")
        if state.issues[key]["failed_trials"] >= 3:
            raise ValueError("Issue reached three failed trials. Request review or finish unresolved.")
    frame = state.manager.load(state.current_ref)
    if not args["columns"] or set(args["columns"]) - set(frame.columns):
        raise ValueError("All affected columns must exist")
    if any(state.issues[key]["column"] not in args["columns"] for key in args["issue_ids"]):
        raise ValueError("Each selected issue must concern an affected column")
    if any(i["column"] in args["columns"] and i["status"] == "awaiting_review" for i in state.issues.values()):
        raise ValueError("An affected column is awaiting human review; do not bypass that decision with another issue ID")
    if any(c["column"] not in args["columns"] for c in args["checks"]):
        raise ValueError("Outcome checks must refer to affected columns")
    if any(key not in state.evidence for key in args["evidence_ids"]):
        raise ValueError("Use existing evidence IDs")
    fingerprint = digest(json.dumps({k: args.get(k) for k in ["kind", "columns", "operation", "parameters", "code", "checks"]}, sort_keys=True).encode())
    if any(c["fingerprint"] == fingerprint and c["base_version"] == state.current_ref.version for c in state.method_candidates.values()):
        raise ValueError("This exact method was already tested on this version. Review its results or make a concrete revision.")
    if args["kind"] == "generated":
        if not args.get("code"):
            raise ValueError("Generated methods require code defining transform(df)")
        result = experiment(state, args)
        candidate_id = result["candidate_id"]
    else:
        operation = args.get("operation")
        if operation not in CATALOG:
            raise ValueError("Choose a catalog operation or use kind generated with transform(df)")
        parameters = dict(args.get("parameters", {}))
        if operation == "convert_data_types" and "target_type" in parameters:
            parameters["target_type"] = canonical_type(parameters["target_type"])
        from .tool_registry import TOOL_SCHEMAS
        schema = next(t["function"]["parameters"] for t in TOOL_SCHEMAS if t["function"]["name"] == operation)
        full_args = {**parameters, "rationale": args["rationale"], "evidence_ids": args["evidence_ids"]}
        errors = list(Draft202012Validator(schema).iter_errors(full_args))
        if errors:
            raise ValueError("Invalid builtin parameters: " + "; ".join(e.message for e in errors))
        touched = parameters.get("columns") or ([parameters["column"]] if "column" in parameters else args["columns"])
        if set(touched) != set(args["columns"]):
            raise ValueError("Method parameters must target exactly the declared columns")
        if operation in {"trim_whitespace", "handle_missing_values"}:
            parameters.setdefault("columns", args["columns"])
        if operation == "handle_missing_values" and parameters["strategy"] in {"drop_rows", "drop_columns"}:
            raise ValueError("Structural changes need request_review; this trial interface preserves rows and columns")
        args = {**args, "parameters": parameters}
        sample = frame.sample(n=min(200, max(1, len(frame) // 2)), random_state=41)
        rest = frame.drop(index=sample.index)
        partitions = [("sample", sample)] + ([("holdout", rest.sample(n=min(200, len(rest)), random_state=73))] if len(rest) else [])
        trials = []
        for partition, before in partitions:
            outcome = getattr(cleaning, operation)(before.copy(deep=True), **parameters)
            effect = builtin_effect(before, outcome.df, operation, args) if outcome.success and outcome.df is not None else None
            trials.append({"partition": partition, "rows": len(before), "success": bool(effect and effect["accepted"]),
                           "error": outcome.error, "effect": effect})
        candidate_id = "builtin-" + uuid4().hex[:10]
        result = {"success": all(t["success"] for t in trials), "candidate_id": candidate_id,
                  "tested": all(t["success"] for t in trials), "trials": trials,
                  "holdout_available": len(partitions) == 2, "message": "Inspect actual trial results before accepting or revising."}
    candidate = {**args, **result, "base_version": state.current_ref.version,
                 "dataset_hash": digest(Path(state.current_ref.path).read_bytes()), "fingerprint": fingerprint}
    candidate["method_hash"] = method_hash(candidate)
    state.method_candidates[candidate_id] = candidate
    for key in args["issue_ids"]:
        if not result["tested"]:
            state.issues[key]["failed_trials"] += 1
    state.decisions.append({"stage": "propose", "candidate_id": candidate_id,
                            **{k: args[k] for k in ["issue_ids", "hypothesis", "assumptions", "expected_effect", "evidence_ids"]}})
    state.workflow_stage = "evaluate"
    return {**result, "hypothesis": args["hypothesis"], "assumptions": args["assumptions"],
            "expected_effect": args["expected_effect"], "evidence_ids": args["evidence_ids"]}


def builtin_effect(before, after, operation, args):
    effect = assess_candidate(before, after, operation, args["columns"], args["parameters"])
    expected = assess_method(before, after, args["columns"], args["checks"])
    effect["rules"].extend(r for r in expected["rules"] if r["rule_name"].startswith("expected:"))
    effect["column_metrics"] = expected["column_metrics"]
    effect["accepted"] = all(r["passed"] for r in effect["rules"])
    return effect


def method_hash(candidate):
    return digest(json.dumps({k: candidate.get(k) for k in ["kind", "columns", "operation", "parameters", "code", "checks"]}, sort_keys=True).encode())


def apply_candidate(executor, candidate):
    state = executor.state
    if any(state.issues[key]["failed_trials"] >= 3 for key in candidate["issue_ids"]):
        raise ValueError("Issue reached three failed trials. Request review or finish unresolved.")
    if any(i["column"] in candidate["columns"] and i["status"] == "awaiting_review" for i in state.issues.values()):
        raise ValueError("An affected column is awaiting human review")
    if not candidate["tested"] or candidate.get("review", {}).get("decision") != "accept":
        raise ValueError("A candidate must pass trials and receive an explicit review before application")
    if candidate["method_hash"] != method_hash(candidate):
        raise ValueError("Candidate method or checks changed after testing; test again")
    if candidate["base_version"] != state.current_ref.version or candidate["dataset_hash"] != digest(Path(state.current_ref.path).read_bytes()):
        raise ValueError("Working data changed since testing. Test again on the current version.")
    if candidate["kind"] == "generated":
        result = executor._apply_experimental_method({"candidate_id": candidate["candidate_id"]})
    else:
        operation = candidate["operation"]
        def full(frame, **parameters):
            outcome = getattr(cleaning, operation)(frame, **parameters)
            if outcome.success and outcome.df is not None:
                effect = builtin_effect(frame, outcome.df, operation, candidate)
                if not effect["accepted"]:
                    return cleaning.CleaningResult(False, error="Full-data candidate checks failed", details={"full_data_effect": effect})
            return outcome
        result = executor._clean(operation, full, {**candidate["parameters"],
            "rationale": candidate["rationale"], "evidence_ids": candidate["evidence_ids"]}, candidate["columns"])
    result["candidate_id"] = candidate["candidate_id"]
    candidate["application"] = {"success": result["success"], "version": state.current_ref.version}
    if not result["success"]:
        operation = candidate.get("operation") if candidate["kind"] == "builtin" else "apply_experimental_method"
        candidate["failed_action_key"] = f"{operation}:{candidate['columns']}"
        for key in candidate["issue_ids"]:
            state.issues[key]["failed_trials"] += 1
    if result["success"]:
        if result.get("no_op"):
            for key in candidate["issue_ids"]:
                if state.issues[key]["kind"] == "finding":
                    state.issues[key]["failed_trials"] += 1
        for key in candidate["issue_ids"]:
            if state.issues[key]["kind"] == "finding" and not result.get("no_op"):
                state.issues[key]["status"] = "resolved"
        refresh(state)
        for previous in state.method_candidates.values():
            if previous.get("failed_action_key") and all(state.issues[k]["status"] == "resolved" for k in previous["issue_ids"]):
                state.failed_actions.pop(previous["failed_action_key"], None)
        state.workflow_stage = "understand"
        if all(i["status"] == "resolved" for i in state.issues.values()):
            state.workflow_stage = "conclude"
        result["validation"] = executor._validate_dataset({})
    return result
