"""Bound unproductive inspection while leaving decisions and methods to the model."""
import json
from copy import deepcopy

MAX_STALLED_ATTEMPTS = 3


def evidence_signature(result):
    # Presentation metadata does not make a repeated page new evidence.
    measured = {k: v for k, v in result.items() if k not in {
        "version", "investigation", "filter", "offset", "next_offset", "cached", "previous_event"}}
    if "value_overview" in measured:
        measured["value_overview"] = {k: v for k, v in measured["value_overview"].items()
                                      if k not in {"offset", "limit", "next_offset", "all_distinct_values_displayed"}}
    return json.dumps(measured, sort_keys=True, default=str)


def signature(arguments, *, measurement=False):
    from .inspection import inspection_query
    query = inspection_query(arguments)
    if measurement:
        query = {k: v for k, v in query.items() if k not in {"offset", "limit"}}
    return json.dumps(query, sort_keys=True)


def inspect(executor, arguments, read):
    from .cleaning_tasks import active
    state = executor.state
    task = active(state) if state.focused_cleaning else None
    task_id = task["id"] if task else None
    version = state.current_ref.version
    scope = f"{version}:{task_id if task else arguments.get('column', 'dataset')}"
    progress = state.inspection_progress.setdefault(scope, {"inspections": 0, "consecutive_stalls": 0, "questions": []})
    history = [e for e in reversed(state.events) if e["tool"] == "inspect_data"
               and e.get("source_version") == version and e["result"].get("success", True)]
    query = signature(arguments)
    prior = next((e for e in history if signature(e["arguments"]) == query), None)
    if prior and (task is None or prior.get("task_id") == task_id):
        return stalled(executor, "This exact inspection already ran on this dataset version; changing its reason does not provide new evidence.",
                       task=task, progress=progress, prior=prior)
    if prior:
        # Another task can consume existing evidence once without a reread or penalty.
        result = deepcopy(prior["result"])
        result.update(cached=True, previous_event=prior["event_id"])
    else:
        try:
            result = read(executor, arguments)
        except ValueError as exc:
            return stalled(executor, f"The inspection returned no evidence: {exc}", task=task, progress=progress)
        measured = evidence_signature(result)
        measurement = signature(arguments, measurement=True)
        same_page = next((e for e in history if e.get("task_id") == task_id
                         and signature(e["arguments"], measurement=True) == measurement
                         and evidence_signature(e["result"]) == measured), None)
        if same_page:
            return stalled(executor, "The changed inspection returned identical evidence. Changing page size or offset alone is not progress.",
                           task=task, progress=progress, prior=same_page)
    progress["inspections"] += 1
    progress["consecutive_stalls"] = 0
    question = arguments.get("question") or arguments["reason"]
    progress["questions"].append(question)
    result["investigation"] = {"new_evidence": prior is None, "question": question,
        "next_action": "Decide from this evidence, or explain the remaining question and useful next view in reason."}
    return result


def stalled(executor, problem, *, task=None, progress=None, prior=None):
    state = executor.state
    version = state.current_ref.version
    if progress is None:
        scope = f"{version}:{task['id'] if task else 'dataset'}"
        progress = state.inspection_progress.setdefault(scope, {"inspections": 0, "consecutive_stalls": 0, "questions": []})
    progress["consecutive_stalls"] += 1
    next_action = ("Choose a different inspection that answers a remaining question: distribution gives actual min/max, signs and IQR counts; "
        "extremes gives smallest/largest observations; filtered gives missing, non_numeric, negative or IQR-outlier examples; "
        "relationships compares two columns. Explain the remaining question and expected evidence in reason. "
        "Alternatively complete an advisory task as reviewed with evidence for retaining the data, test a justified repair, "
        "or flag a specific unresolved business decision. A statistical threshold is not an observed value.")
    result = {"success": False, "error_kind": "inspection_no_progress", "error": problem,
              "next_action": next_action, "consecutive_stalls": progress["consecutive_stalls"],
              "remaining_attempts": max(0, MAX_STALLED_ATTEMPTS-progress["consecutive_stalls"])}
    if prior:
        cached_result = deepcopy(prior["result"])
        cached_result.pop("investigation", None)  # Its old new_evidence flag is no longer true.
        result.update(cached=True, previous_event=prior["event_id"], cached_result=cached_result)
    if progress["consecutive_stalls"] >= MAX_STALLED_ATTEMPTS:
        reason = "Investigation unresolved: three consecutive tool requests supplied no new evidence or a valid next action. " + problem
        if task:
            task.update(status="needs_review", reason=reason, assessed_version=version)
            if task.get("measured"):
                state.flagged.update({c: reason for c in task["columns"]})
            state.validation = None
            result.update(task_deferred=task["id"], next_action="This task remains unresolved and was deferred for review. Continue the next independent task; do not claim it was cleaned.")
        else:
            executor.stop("inspection_stalled", reason)
    return result
