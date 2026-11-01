"""Bounded model-authored revisions, executed only through the existing tool boundary."""
import json
import time
from copy import deepcopy
from pathlib import Path

from .workflow import STRING, tool
from .repair_history import implementation_key, model_history
from jsonschema import Draft202012Validator
from .expert_generator import generate_candidate

REPAIR_TOOL = tool("repair_method", "Return a corrected complete transform(df) and explain the correction.",
                   {"code": STRING, "hypothesis": STRING}, ["code", "hypothesis"])
PROMPT = Path(__file__).resolve().parent / "prompts" / "code_correction.md"
PROPOSAL = {"type": "object", "additionalProperties": False,
            "properties": {k: STRING for k in ("supported_interpretations", "preservation", "ambiguities")},
            "required": ["supported_interpretations", "preservation", "ambiguities"]}


def correction_context(state, executor, current, result, retry, max_retries, route):
    """One diagnostic, relevant observations, and compact history; full evidence stays in the audit."""
    recovery = (result.get("recovery_prompt") or {}).get("context", {})
    diagnostic = result.get("diagnostic") or recovery.get("diagnostic") or {}
    summary = result.get("failure_summary") or {}
    problem = diagnostic.get("problem") or result.get("error") or result.get("message") or "Trial failed"
    lines = [line.strip() for line in str(problem).splitlines() if line.strip()]
    history = [{**h, "problem": h["problem"][-240:]} for h in model_history(state)[-6:]]
    from .cleaning_tasks import model_view
    focused = model_view(state, executor) if state.focused_cleaning else {}
    from .value_interpretation import plans
    return {"attempt": retry, "max_retries": max_retries, "route": route,
            "cleaning_focus": focused.get("cleaning_focus"),
            "value_interpretation": focused.get("value_interpretation") or plans(state, current["columns"], current.get("checks", [])),
            "failed_method": {k: current[k] for k in ("code", "hypothesis", "columns", "checks", "value_assessment") if k in current},
            "failure": {"diagnostic": {"stage": diagnostic.get("stage", route),
                "problem": lines[-1] if lines else "Trial failed", "location": diagnostic.get("location"),
                "correction": diagnostic.get("correction"), "runtime_guidance": diagnostic.get("runtime_guidance")},
                "sandbox_logs": recovery.get("sandbox_logs", diagnostic.get("sandbox_logs", [])),
                "failed_checks": summary.get("failed_checks") or recovery.get("failed_checks", []),
                "lost_values": summary.get("lost_values") or recovery.get("lost_values", []),
                "repair_error": result.get("repair_error")},
            "observations": recovery.get("working_columns", {}),
            "outstanding": focused.get("outstanding", executor.progress()),
            "repair_history": [h for h in history if not state.focused_cleaning
                               or set(h.get("columns") or []) & set(current.get("columns", []))]}


def execute_and_fix_loop(arguments, initial_result, *, executor, generate, max_retries=4):
    """Four bounded local corrections, then one Groq-authored replacement.

    The initial failed trial is not a correction. Invalid/unchanged local replies
    are unsuccessful correction attempts too, but never count as Docker executions.
    Infrastructure failures stop immediately and never trigger Groq.
    """
    state = executor.state
    current, result = dict(arguments), initial_result
    seen = {implementation_key(current)}
    attempts = []
    for retry in range(1, min(max_retries, 4) + 1):
        if result.get("success") or state.finished or time.monotonic() >= state.deadline:
            break
        route = (result.get("recovery_prompt") or {}).get("case")
        if route in {"sandbox_unavailable", "approval_required", "stale_candidate"}:
            break
        if state.on_event:
            state.on_event({"phase": f"correcting generated method · retry {retry}/4", "stage": "model"})
        selected_tool = deepcopy(REPAIR_TOOL)
        if route in {"data_loss", "validation", "conversion", "imputation"}:
            selected_tool["function"]["parameters"]["properties"]["proposal"] = PROPOSAL
            selected_tool["function"]["parameters"]["required"].append("proposal")
        messages = [{"role": "system", "content": PROMPT.read_text(encoding="utf-8")},
                    {"role": "user", "content": json.dumps(correction_context(state, executor, current, result, retry, 4, route))}]
        log = {"turn": state.current_turn, "source": "self_correction", "retry": retry}
        attempt = {"attempt": retry}
        try:
            response = generate(messages, [selected_tool], timeout=state.deadline-time.monotonic())
            log.update(provider=response.get("provider"), model=response.get("model"), usage=response.get("usage"),
                       timing=response.get("timing"), finish_reason=response.get("finish_reason"),
                       response_issue=response.get("response_issue"), raw_response=response.get("raw_response"))
            attempt.update(finish_reason=response.get("finish_reason"), response_issue=response.get("response_issue"))
            calls = response.get("tool_calls") or []
            repair = calls[0].get("arguments") if len(calls) == 1 and calls[0].get("name") == "repair_method" else None
            errors = list(Draft202012Validator(selected_tool["function"]["parameters"]).iter_errors(repair))
            if errors:
                attempt["raw_response"] = response.get("raw_response")
                result = {**result, "repair_error": "Return a complete correction matching the schema: " + "; ".join(e.message for e in errors)}
                attempt["error"] = result["repair_error"]
                continue
            revised = {**current, "code": repair["code"], "hypothesis": repair["hypothesis"]}
            attempt.update(code=repair["code"], hypothesis=repair["hypothesis"])
            if repair.get("proposal"):
                revised["hypothesis"] += " Repair proposal: " + json.dumps(repair["proposal"])
            key = implementation_key(revised)
            if key in seen:
                result = {**result, "repair_error": "This exact code already failed. Change its implementation, not just its explanation."}
                attempt["error"] = result["repair_error"]
                continue
            seen.add(key)
            current = revised
            result = json.loads(executor.execute("test_generated", current, origin="self_correction"))
            attempt.update(error=result.get("error"), diagnostic=result.get("diagnostic"),
                           failure_summary=result.get("failure_summary"), success=bool(result.get("success")))
            log.update(tool="test_generated", args=current, result_preview=json.dumps(result)[:300])
        except Exception as exc:
            # Provider exception details can contain request information.
            attempt["error"] = f"Local correction failed ({type(exc).__name__})"
            result = {**result, "repair_error": attempt["error"]}
            executor.stop("local_correction_error", attempt["error"])
        finally:
            attempts.append(attempt)
            log["outcome"] = attempt
            state.step_log.append(log)
            state.persist_trace()
        if result.get("success"):
            return current, result
    if result.get("success") or state.finished:
        return current, result
    if len(attempts) == 4 and time.monotonic() < state.deadline:
        proposal = generate_candidate(executor, current, result, attempts=attempts)
        if proposal["decision"] != "generated":
            executor.stop("expert_generation_failed", proposal.get("error") or proposal.get("hypothesis") or "Groq could not generate a justified method")
            return current, {**result, "expert_generation": proposal}
        revised = {**current, "code": proposal["code"], "hypothesis": proposal["hypothesis"]}
        if implementation_key(revised) in seen:
            executor.stop("expert_generation_failed", "Groq returned an unchanged failed implementation")
            return current, {**result, "expert_generation": proposal}
        result = json.loads(executor.execute("test_generated", revised, origin="groq_generation"))
        current = revised
        if result.get("success"):
            return current, result
    if not state.finished:
        executor.stop("correction_exhausted", "Generated method did not pass the correction pipeline; no builtin fallback is permitted")
    return current, result
