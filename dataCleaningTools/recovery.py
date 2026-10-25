"""Select focused feedback from outcomes; never select or execute a repair."""
from pathlib import Path

from .effects import present

PROMPTS = Path(__file__).resolve().parents[1] / "agents" / "prompts" / "recovery"


def build_prompt(executor, tool, arguments, result):
    state = executor.state
    candidate_id = arguments.get("candidate_id")
    candidate = state.method_candidates.get(candidate_id, {}) if isinstance(candidate_id, str) else {}
    method = candidate if tool == "apply_candidate" else arguments
    operation = method.get("operation")
    operation = operation if isinstance(operation, str) else None
    raw_columns = method.get("columns", [])
    columns = [c for c in raw_columns if isinstance(c, str)] if isinstance(raw_columns, list) else []
    parameters = method.get("parameters", {})
    details = result.get("details") if isinstance(result.get("details"), dict) else {}
    effect = result.get("effect") or details.get("full_data_effect") or {}
    rules = effect.get("rules", []) + result.get("rules", []) + (result.get("validation") or {}).get("rules", [])
    failed = [r for r in rules if not r.get("passed")]
    trials = []
    for trial in result.get("trials", []):
        trial_failed = [r for r in (trial.get("effect") or {}).get("rules", []) if not r.get("passed")]
        if not trial.get("success"):
            trials.append({"partition": trial["partition"], "error": trial.get("error"), "failed_checks": trial_failed})
            failed.extend(trial_failed)
    error = str(result.get("error") or result.get("message") or "")
    errors = " ".join([error] + [str(t.get("error") or "") for t in trials]).lower()
    generated = bool(method.get("code")) or method.get("kind") == "generated"
    execution_kinds = [result.get("error_kind"), details.get("error_kind")] + [t.get("error_kind") for t in result.get("trials", [])]
    if tool == "model_response":
        case = "truncated_response" if result.get("error_kind") == "truncated" else "response_format"
    elif result.get("approval_required"):
        case = "approval_required"
    elif result.get("no_op"):
        case = "no_change"
    elif result.get("success", True):
        return None
    elif result.get("error_kind") == "invalid_tool_arguments" or errors.startswith((
            "invalid builtin parameters", "missing argument", "provide either operation", "generated code requires",
            "choose a catalog", "unknown columns", "unknown candidate_id", "checks must refer", "parameters must target", "view=")):
        case = "arguments"
    elif "changed since testing" in errors or "changed after testing" in errors or "tested data or method changed" in errors:
        case = "stale_candidate"
    elif generated and ("sandbox_unavailable" in execution_kinds or
            (not any(execution_kinds) and any(t.get("setup") for t in result.get("trials", []))) or
            (not any(execution_kinds) and any(s in errors for s in ["docker unavailable", "docker is unavailable", "runtime unavailable", "connection refused"]))):
        case = "sandbox_unavailable"
    elif tool == "finish":
        case = "final_validation"
    elif any(r.get("rule_name", "").startswith("no_new_missing:") for r in failed):
        case = "data_loss"
    elif any(r.get("rule_name", "") in {"non_empty", "row_count", "columns", "row_identity"}
             or r.get("rule_name", "").startswith("untouched:") for r in failed):
        case = "validation"
    elif operation == "handle_missing_values":
        case = "imputation"
    elif operation in {"convert_data_types", "clean_numeric_string"} and (not failed or any(r.get("rule_name", "").startswith("target_type:") for r in failed)):
        case = "conversion"
    elif failed:
        case = "validation"
    elif generated and (error or any(t.get("error") for t in trials)):
        case = "sandbox_execution"
    elif operation in {"convert_data_types", "clean_numeric_string"}:
        case = "conversion"
    else:
        case = "general"
    context = {"tool": tool, "operation": operation, "columns": columns, "parameters": parameters,
        "error": error, "failed_checks": failed, "failed_trials": trials,
        "working_version": state.current_ref.version, "candidate_version": candidate.get("base_version"),
        "outstanding": executor.progress(), "changed_examples": effect.get("changed_examples", [])[:5]}
    if columns:
        frame = state.manager.load(state.current_ref)
        context["working_columns"] = {c: {"dtype": str(frame[c].dtype), "missing": int((~present(frame[c])).sum()),
            "examples": [str(value)[:120] for value in frame[c].dropna().head(5)]} for c in columns[:10] if c in frame}
    return {"case": case, "instruction": (PROMPTS / f"{case}.md").read_text(encoding="utf-8").strip(),
            "context": context}
