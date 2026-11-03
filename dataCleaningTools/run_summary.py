"""Plain summaries of a finished cleaning run for the dashboard; no Streamlit, no data loading."""
from __future__ import annotations

from .approvals import pending
from .decisions import open_decisions
from .cleaning_tasks import CATEGORIES

# Task statuses grouped by what they mean for the reader.
RESOLVED = {"done", "reviewed", "not_required"}
FAILED = {"dropped", "blocked"}
WAITING = {"awaiting_approval", "needs_review"}

STOP_REASONS = {
    "completed": "Finished: every check passed",
    "completed_with_exceptions": "Finished, with items for you to review",
    "incomplete": "Finished, but some required checks still fail",
    "time_budget": "Stopped: the run time budget ran out",
    "max_turns": "Stopped: the model-turn limit was reached",
    "provider_error": "Stopped: the local model returned an error",
    "request_timeout": "Stopped: a model request timed out",
    "sandbox_unavailable": "Stopped: Docker was not available",
    "controller_error": "Stopped: internal error while preparing a step",
    "no_tool_calls": "Stopped: the model gave no usable actions",
    "context_budget": "Stopped: a request was too large for the model context",
    "dry_run": "Dry run: nothing was changed",
    "deterministic_completed": "Finished: deterministic baseline",
}


def task_version(events, task_id):
    """The dataset version a task's change was committed as, if any."""
    return next((e["version"] for e in reversed(events) if e.get("task_id") == task_id
                 and e["tool"] == "apply_candidate" and e["result"].get("success")), None)


def summarize(result) -> dict:
    meta = result.metadata
    tasks = meta.get("cleaning_tasks", [])
    events = meta.get("events", [])
    waiting = pending(result)
    applied = result.change_log.successful_ops()
    report = meta.get("report_summary") or {}
    lost = report.get("values_coerced_to_missing")
    if lost is None:
        lost = sum(len((r.metadata.get("effect") or {}).get("lost_values", [])) for r in applied)
    open_items = open_decisions(result)
    # One per decision: a dropped task and the tasks it blocked or froze share their columns.
    needs_you = len(waiting) + len(open_items)
    needs_you_names = ([f"approve {', '.join(w['columns'])}" for w in waiting]
                       + [f"decide {item['key']}" for item in open_items])
    status = result.validation.status.value

    categories = []
    for key, title in CATEGORIES:
        group = [t for t in tasks if t["category"] == key]
        counts = {"total": len(group), "resolved": sum(t["status"] in RESOLVED for t in group),
                  "failed": sum(t["status"] in FAILED for t in group),
                  "waiting": sum(t["status"] in WAITING for t in group),
                  "pending": sum(t["status"] == "pending" for t in group)}
        if key == "understanding":
            state = "done"
        elif key == "validation":
            state = {"passed": "done", "partial": "waiting", "failed": "failed"}.get(status, "none")
        elif not group:
            state = "none"
        else:
            state = ("failed" if counts["failed"] else "waiting" if counts["waiting"] + counts["pending"] else "done")
        categories.append({"key": key, "title": title, "state": state, **counts})

    limits = meta.get("limits", {})
    board = [{"id": t["id"], "category": t["category"], "columns": t["columns"], "status": t["status"],
              "turns": t.get("turns", 0), "max_turns": limits.get("max_task_turns", 6),
              "version": task_version(events, t["id"]) or t.get("applied_version"),
              "reason": t.get("reason") or "", "blocked_by": t.get("blocked_by")}
             for t in tasks if t["category"] != "understanding"]

    trail = [{"version": result.source_dataset.version, "label": "original"}]
    if applied:
        trail.append({"version": applied[0].source_version, "label": "working copy"})
    trail += [{"version": r.result_version, "label": f"{r.operation} · {', '.join(r.columns)}",
               "approved": r.approval_obtained} for r in applied]

    changed = {}
    for record in applied:
        effect = record.metadata.get("effect") or {}
        if effect.get("changed_cells") and len(record.columns) == 1:
            changed[record.columns[0]] = changed.get(record.columns[0], 0) + effect["changed_cells"]
    before, after = report.get("before") or {}, report.get("after") or {}
    health = []
    for column, missing_before in (before.get("missing") or {}).items():
        missing_after = (after.get("missing") or {}).get(column)
        dtype_before, dtype_after = (before.get("dtypes") or {}).get(column), (after.get("dtypes") or {}).get(column)
        if missing_before or missing_after or dtype_before != dtype_after or changed.get(column):
            health.append({"column": column, "rows_before": before.get("rows"), "rows_after": after.get("rows"),
                           "missing_before": missing_before, "missing_after": missing_after,
                           "dtype_before": dtype_before, "dtype_after": dtype_after,
                           "values_changed": changed.get(column, 0)})

    stop = STOP_REASONS.get(meta.get("stop_reason", ""), meta.get("stop_reason", "unknown"))
    if meta.get("host_decisions") and not waiting:
        stop = "Finished; your decisions were applied"
    return {
        "status": status,
        "needs_you": needs_you, "needs_you_names": needs_you_names,
        "stop": stop,
        "accepted": list(meta.get("waived") or {}),  # columns the host accepted as they are
        "final_version": result.final_dataset.version,
        "turns": meta.get("turns_used", 0), "max_turns": limits.get("max_turns"),
        "seconds": meta.get("elapsed_seconds", 0), "model": meta.get("model"),
        "kpis": {"applied": len(applied), "awaiting": len(waiting),
                 "dropped_or_blocked": sum(t["status"] in FAILED for t in tasks), "set_to_missing": lost},
        "categories": categories, "board": board, "trail": trail, "health": health,
    }
