"""Bounded correction of the tool envelope, before any generated-code retries."""
import json
import time
from pathlib import Path

from jsonschema import Draft202012Validator

from . import workflow
from .cleaning_tasks import active, closed, context
from .contracts import canonical_type

PROMPT = Path(__file__).with_name("prompts") / "request_correction.md"


def correct_request(name, arguments, result, *, executor, generate, max_retries=2):
    state = executor.state
    task = active(state) if state.focused_cleaning else None
    for attempt in range(1, max_retries + 1):
        if result.get("success") or closed(state, task):
            break
        if (result.get("recovery_prompt") or {}).get("case") != "arguments":
            break
        if time.monotonic() >= state.deadline:
            break
        nested = arguments.get("parameters", {})
        generated = name == "test_generated" or arguments.get("code") or (
            isinstance(nested, dict) and nested.get("code")) or (task and task.get("generated_required"))
        target = "test_generated" if generated else "test_builtin"
        # The task's own tool list: other operations' parameters would only invite invalid additions.
        offered = workflow.available_tools(state) if state.focused_cleaning else workflow.SCHEMAS_LIST
        selected = next((t for t in offered if t["function"]["name"] == target),
                        next(t for t in workflow.SCHEMAS_LIST if t["function"]["name"] == target))
        log = {"turn": state.current_turn, "source": "request_correction", "attempt": attempt, "target": target}
        try:
            from .value_interpretation import plans
            columns = task["columns"] if task else arguments.get("columns", [])
            value_plan = plans(state, columns) if isinstance(columns, list) and all(isinstance(c, str) for c in columns) else None
            response = generate([
                {"role": "system", "content": PROMPT.read_text(encoding="utf-8")},
                {"role": "user", "content": json.dumps({"failed_tool": name, "failed_arguments": arguments,
                    "diagnostic": result.get("diagnostic") or result.get("error"),
                    "value_interpretation": value_plan,
                    "cleaning_focus": context(state) if state.focused_cleaning else None})}],
                [selected], timeout=state.deadline-time.monotonic())
            log.update(model=response.get("model"), usage=response.get("usage"), raw_response=response.get("raw_response"))
            calls = response.get("tool_calls") or []
            revised = calls[0].get("arguments") if len(calls) == 1 and calls[0].get("name") == target else None
            errors = list(Draft202012Validator(workflow.SCHEMA[target]).iter_errors(revised))
            if errors:
                result = {**result, "error": "Correct the request schema: " + "; ".join(e.message for e in errors)}
                continue
            if isinstance(arguments.get("columns"), list) and revised["columns"] != arguments["columns"]:
                result = {**result, "error": "Request correction must keep the original selected columns"}
                continue
            def outcomes(checks):
                return {(c.get("column"), "numeric" if canonical_type(c.get("kind")) == "float" else canonical_type(c.get("kind")))
                        for c in checks if isinstance(c, dict)}
            intended = outcomes(arguments.get("checks", []))
            known = set(workflow.CHECKS["items"]["properties"]["kind"]["enum"])
            intended = {(column, kind) for column, kind in intended if kind in known}
            if not intended.issubset(outcomes(revised.get("checks", []))):
                result = {**result, "error": "Correct the request without weakening its intended outcomes"}
                continue
            name, arguments = target, revised
            result = json.loads(executor.execute(name, arguments, origin="request_correction"))
            result["repaired_tool"] = name
        except Exception as exc:
            log["error"] = f"Request correction failed ({type(exc).__name__})"
            if name != "test_builtin":
                executor.stop("request_correction_failed", log["error"])
            break
        finally:
            log["result"] = {"success": result.get("success"), "error": result.get("error")}
            state.step_log.append(log)
            state.persist_trace()
    if not closed(state, task) and (result.get("recovery_prompt") or {}).get("case") == "arguments":
        if name == "test_builtin":
            # A builtin that could not be expressed is a failed attempt, not a dead end: the model's next
            # turn can revise it or move to generated code (local correction, then Groq).
            result = {**result, "request_correction_exhausted": True,
                      "error": f"{result.get('error') or 'Invalid builtin request'}. This builtin request could not be "
                               "corrected automatically. Revise its parameters, or write generated code with test_generated."}
        else:
            executor.stop("request_correction_failed", "Could not construct a valid cleaning request within the request-correction limit")
    return name, arguments, result
