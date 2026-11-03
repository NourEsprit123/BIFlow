"""Open items only a person can settle after a run: dropped, blocked and needs-review tasks.

They are grouped into one decision per column (a dropped task also blocks or freezes the other tasks on
its columns). A decision is applied to the saved run without model calls: "accept" records a host waiver
for the column, "fill" fills its missing values through the checked builtin, with a suggested strategy
(led by the profiling model's imputation choice, see fill_suggestions) or a value the person typed.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import pandas as pd

from .tool_registry import ToolExecutor

OPEN = {"dropped", "blocked", "needs_review"}
# What a drop means for the person deciding; the technical detail stays available beneath.
DROP_TEXT = {
    "no_tool_calls": "The model could not decide how to handle this.",
    "turn_budget": "The model used all its attempts without resolving this.",
    "attempt_budget": "Several different fixes were tried and none passed the checks.",
    "correction_exhausted": "Generated fixes kept failing the checks.",
    "expert_generation_failed": "Neither the local model nor the fallback model could write a fix that passes the checks.",
    "request_correction_failed": "The model could not form a valid fix request.",
    "local_correction_error": "The local model failed while correcting its fix.",
    "tool_execution_error": "A cleaning step failed to run.",
    "sandbox_unavailable": "Docker was not available to test generated code.",
    "sandbox_timeout": "Docker did not answer in time to test generated code.",
    "context_budget": "The evidence was too large for the local model.",
}


def decision_key(task):
    return ",".join(task["columns"]) or "dataset"


def plain_reason(reason):
    """Drop the internal "Dropped (code): " prefix; keep the explanation."""
    return re.sub(r"^(Dropped|Blocked) \([a-z_]+\):\s*", "", reason or "").strip()


def open_decisions(result) -> list[dict]:
    meta = result.metadata
    missing_after = ((meta.get("report_summary") or {}).get("after") or {}).get("missing") or {}
    groups = {}
    for task in meta.get("cleaning_tasks", []):
        if task["status"] not in OPEN:
            continue
        group = groups.setdefault(decision_key(task), {"key": decision_key(task), "columns": task["columns"], "tasks": []})
        group["tasks"].append({"id": task["id"], "category": task["category"], "status": task["status"],
                               "reason": plain_reason(task.get("reason")), "drop_reason": task.get("drop_reason")})
    for group in groups.values():
        group["missing"] = sum(missing_after.get(c, 0) for c in group["columns"])
        group["can_fill"] = (len(group["columns"]) == 1 and group["missing"] > 0
                             and any(t["category"] == "missing" for t in group["tasks"]))
        lead = next((t for t in group["tasks"] if t["status"] == "dropped"), group["tasks"][0])
        group["summary"] = (DROP_TEXT.get(lead["drop_reason"]) or lead["reason"]
                            or f"{lead['category'].title()} task {lead['status'].replace('_', ' ')}")
        group["detail"] = lead["reason"] if lead["drop_reason"] in DROP_TEXT else ""
        group["suggestions"] = fill_suggestions(result, group["columns"][0]) if group["can_fill"] else []
    return list(groups.values())


# Profiling strategies (Agent 1's imputation_strategy / imputation_plan) and the builtin that performs them.
FILL_STRATEGIES = {"median": "fill_median", "mean": "fill_mean", "mode": "fill_mode", "most_frequent": "fill_mode"}
FILL_LABELS = {"fill_median": "Median", "fill_mean": "Mean", "fill_mode": "Most frequent value"}


def _profiling_hint(result, column):
    """The profiling model's imputation choice for this column and its reasoning, if it gave one."""
    try:
        from pathlib import Path
        context = json.loads((Path(result.metadata["result_path"]).parent / "cleaning_context.json").read_text(encoding="utf-8"))
        report = context["profiling_report_copy"]
    except (KeyError, OSError, ValueError):
        return None, ""
    profile = report.get("column_profiles", {}).get(column, {})
    plan = (report.get("imputation_plan") or {}).get(column) or {}
    strategy = str(plan.get("strategy") or profile.get("imputation_strategy") or "").strip().lower()
    reason = str(profile.get("agent_reasoning") or profile.get("business_interpretation") or "").strip()
    return FILL_STRATEGIES.get(strategy), reason[:240]


def fill_suggestions(result, column):
    """Fill options for a column with blanks, led by the profiling model's choice: each names the builtin
    strategy and the value it would write, measured on the current final version."""
    from .cleaning import _whole_numbers
    try:
        series = pd.read_csv(result.final_dataset.path, usecols=[column])[column]
    except (OSError, ValueError, KeyError):
        return []
    present = series.dropna()
    if present.empty:
        return []
    numeric = pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)
    whole = _whole_numbers(series)
    def shown(value):
        return int(round(value)) if whole else round(float(value), 4)
    measured = {"fill_mode": present.mode().iloc[0]}
    if numeric:
        measured = {"fill_median": shown(present.median()), "fill_mean": shown(present.mean()), **measured}
        if whole:
            measured["fill_mode"] = int(measured["fill_mode"])
    hinted, reason = _profiling_hint(result, column)
    if hinted not in measured:
        hinted, reason = ("fill_median" if numeric else "fill_mode"), ""
    order = [hinted] + [k for k in measured if k != hinted]
    return [{"strategy": k, "label": FILL_LABELS[k], "value": measured[k], "recommended": k == hinted,
             "source": ("profiling" if reason else "rule") if k == hinted else "measured",
             "reason": reason if k == hinted else ""} for k in order]


def _fill_value(frame, column, text):
    """Typed fill value: numbers for numeric columns, the text itself otherwise."""
    if pd.api.types.is_numeric_dtype(frame[column]) and not pd.api.types.is_bool_dtype(frame[column]):
        number = float(text)
        return int(number) if number.is_integer() else number
    return text


def _settle_notes(state, columns):
    """Unresolved notes that name a column the host just settled are no longer open. The model's finish
    note "Order_ID" kept a run partial after the host had accepted Order_ID as it is."""
    names = [re.compile(rf"^{re.escape(c)}(?=$|[\s:,(.\-])") for c in columns]
    keep = lambda note: not any(name.match(str(note)) for name in names)
    state.model_unresolved = [note for note in state.model_unresolved if keep(note)]
    state.unresolved = [note for note in state.unresolved if keep(note)]


def apply(state, choices):
    """choices maps a decision key to {"action": "accept", "note": ...} or {"action": "fill", "value": ...}."""
    executor = ToolExecutor(state)
    focused, state.focused_cleaning = state.focused_cleaning, False  # the tasks are closed; no task scoping applies
    log = []
    try:
        for key, choice in choices.items():
            tasks = [t for t in state.cleaning_tasks if t["status"] in OPEN and decision_key(t) == key]
            action = (choice or {}).get("action")
            if not tasks or action not in {"accept", "fill"}:
                continue
            columns = tasks[0]["columns"]
            entry = {"decision": key, "action": action, "at": datetime.now(timezone.utc).isoformat(),
                     "base_version": state.current_ref.version}
            # These columns were frozen by the tasks being settled here.
            previous_flags = {c: state.flagged.pop(c) for c in columns if c in state.flagged}
            if action == "accept":
                note = (choice.get("note") or "").strip() or "accepted as is"
                state.waived.update({c: note for c in columns})
                _settle_notes(state, columns)
                for task in tasks:
                    task.update(status="reviewed", reason=f"Accepted by host: {note}",
                                assessed_version=state.current_ref.version)
                entry.update(applied=True, note=note)
            else:
                column = columns[0]
                strategy = choice.get("strategy")
                if strategy in FILL_LABELS:
                    value, parameters = FILL_LABELS[strategy].lower(), {"strategy": strategy}
                else:
                    try:
                        value = _fill_value(state.manager.load(state.current_ref), column, str(choice.get("value", "")).strip())
                    except ValueError:
                        value = None
                    if value in (None, ""):
                        state.flagged.update(previous_flags)
                        entry.update(applied=False, error="Enter a fill value that matches the column")
                        log.append(entry)
                        continue
                    parameters = {"strategy": "fill_constant", "fill_value": value}
                trial = json.loads(executor.execute("test_builtin", {
                    "hypothesis": f"Host decision: fill missing {column} with {value!r}", "columns": [column],
                    "operation": "handle_missing_values", "parameters": parameters},
                    origin="host_decision"))
                applied = (json.loads(executor.execute("apply_candidate", {"candidate_id": trial["candidate_id"],
                           "assessment": f"Fill value chosen by host for {column}"}, origin="host_decision"))
                           if trial.get("success") else trial)
                if applied.get("success"):
                    for task in tasks:
                        task.update(status="reviewed", assessed_version=state.current_ref.version,
                                    reason=f"Filled by host with {value!r} as {state.current_ref.version}")
                    entry.update(applied=True, value=value, version=state.current_ref.version)
                    _settle_notes(state, columns)
                else:
                    state.flagged.update(previous_flags)
                    entry.update(applied=False, value=value, error=str(applied.get("error") or "Fill did not pass its checks"))
            log.append(entry)
    finally:
        state.focused_cleaning = focused
        state.validation = None
    state.host_decisions.extend(log)
    return log
