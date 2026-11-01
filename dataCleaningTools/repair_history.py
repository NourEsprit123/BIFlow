"""Run-scoped failure memory independent of trimmed conversation history."""
import ast
import hashlib
import json

from .contracts import model_arguments


def implementation_key(arguments):
    args = model_arguments("test_generated" if arguments.get("code") else "test_builtin", arguments)
    code = args.get("code")
    if isinstance(code, str):
        try:
            code = ast.dump(ast.parse(code), include_attributes=False)
        except SyntaxError:
            code = code.strip()
    parameters = args.get("parameters", {})
    if not code:
        from .workflow import builtin_parameters
        try:
            parameters = builtin_parameters(args.get("operation"), parameters, args.get("columns", []))
        except (ValueError, TypeError):
            pass
    columns = args.get("columns", [])
    value = {"columns": sorted(columns, key=str) if isinstance(columns, list) else columns, "code": code,
             "operation": args.get("operation"), "parameters": parameters}
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def repeated_failure(state, arguments):
    # Called only after public validation; malformed requests cannot hit this cache.
    key = implementation_key(arguments)
    return next((item for item in reversed(state.repair_history)
                 if item["version"] == state.current_ref.version and item["key"] == key
                 and item["route"] in {"sandbox_execution", "data_loss", "validation", "conversion", "imputation"}
                 and not item["success"]), None)


def remember(state, arguments, result):
    state.repair_history.append({"attempt_id": f"repair-{len(state.repair_history)+1}",
        "version": state.current_ref.version, "key": implementation_key(arguments),
        "arguments": arguments, "success": bool(result.get("success")),
        "route": (result.get("recovery_prompt") or {}).get("case"),
        "error": result.get("error"), "candidate_id": result.get("candidate_id"),
        "failure_summary": result.get("failure_summary"), "diagnostic": result.get("diagnostic"),
        "expert_feedback": result.get("expert_feedback")})


def model_history(state):
    # Full methods and evidence stay in the trace; send compact outcomes each turn.
    return [{"attempt_id": item["attempt_id"], "version": item["version"], "key": item["key"],
             "columns": item["arguments"].get("columns"), "operation": item["arguments"].get("operation"),
             "route": item["route"], "success": item["success"],
             "problem": (item.get("failure_summary") or {}).get("reason") or (item.get("error") or "")[-600:]}
            for item in state.repair_history[-12:]]
