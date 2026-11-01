"""Host decisions on changes that waited for approval, applied to a finished run without model calls.

Approving re-runs the recorded method through the same test and full-data checks as during the run,
on the run's current final version. Rejecting retains the data. The result is then revalidated.
"""
from __future__ import annotations

import json
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from .agent1_adapter import parse_profiling_report
from .tool_registry import AgentSessionState, ToolExecutor
from .versioning import DatasetVersionManager


def approval_event(events, step_id):
    """The latest event whose change stopped at this approval."""
    return next((e for e in reversed(events) if e["result"].get("approval_required")
                 and e["result"].get("step_id") == step_id), None)


def pending(result):
    """Changes awaiting a host decision, with what each would do."""
    meta = result.metadata
    rows = []
    for task in meta.get("cleaning_tasks", []):
        if task["status"] != "awaiting_approval":
            continue
        event = approval_event(meta.get("events", []), task["step_id"]) or {"arguments": {}, "result": {}}
        candidate = meta.get("method_candidates", {}).get(event["arguments"].get("candidate_id"), {})
        rows.append({"task_id": task["id"], "category": task["category"], "columns": task["columns"],
                     "step_id": task["step_id"], "message": task.get("reason", ""),
                     "impact": event["result"].get("impact"), "method": candidate.get("kind"),
                     "operation": candidate.get("operation"), "parameters": candidate.get("parameters"),
                     "code": candidate.get("code"), "hypothesis": candidate.get("hypothesis")})
    return rows


def restore(result):
    """Rebuild a finished run's session from its saved result and working context."""
    meta = result.metadata
    run_dir = Path(meta["result_path"]).parent
    context = json.loads((run_dir / "cleaning_context.json").read_text(encoding="utf-8"))
    report = parse_profiling_report(context["profiling_report_copy"])
    state = AgentSessionState(manager=DatasetVersionManager(run_dir.parent), dataset_id=run_dir.name,
                              current_ref=result.final_dataset, source_ref=result.source_dataset,
                              working_report=context["profiling_report_copy"])
    for name in state.audit():
        if name in meta:
            setattr(state, name, deepcopy(meta[name]))
    if "required_targets" not in meta:
        # Runs saved before these fields were persisted: derive them as DataCleaningAgent.run does.
        state.required_targets = {**report.etl_hints.type_casting_targets,
                                  **{c: p.etl_cast_to for c, p in report.column_profiles.items()
                                     if p.etl_cast_to and p.etl_cast_to.lower() != "none"}}
        state.required_missing = [c for c, p in report.column_profiles.items() if p.missing_count > 0]
        state.expected_columns = list(result.source_dataset.columns)
    state.focused_cleaning = bool(state.cleaning_tasks)
    state.stop_reason = meta.get("stop_reason", "completed")
    state.finish_summary = meta.get("finish_summary", "")
    state.current_turn = meta.get("turns_used", 0)
    state.llm_model, state.llm_provider = meta.get("model"), meta.get("provider")
    state.run_started = time.monotonic() - meta.get("elapsed_seconds", 0)
    return state, report


def _retest_arguments(candidate):
    arguments = {"hypothesis": candidate["hypothesis"], "columns": candidate["columns"]}
    if candidate["kind"] == "generated":
        return "test_generated", {**arguments, "code": candidate["code"], "checks": candidate.get("checks", [])}
    parameters = {k: v for k, v in candidate.get("parameters", {}).items() if k not in {"column", "columns", "subset"}}
    return "test_builtin", {**arguments, "operation": candidate["operation"], "parameters": parameters}


def apply_decisions(state, decisions):
    """decisions maps step_id -> "approve" or "reject". Returns the decision log entries."""
    executor = ToolExecutor(state)
    focused, state.focused_cleaning = state.focused_cleaning, False  # tasks are closed; no task scoping applies
    log = []
    try:
        for task in state.cleaning_tasks:
            decision = decisions.get(task.get("step_id")) if task["status"] == "awaiting_approval" else None
            if decision not in {"approve", "reject"}:
                continue
            entry = {"task_id": task["id"], "step_id": task["step_id"], "decision": decision,
                     "at": datetime.now(timezone.utc).isoformat(), "base_version": state.current_ref.version}
            event = approval_event(state.events, task["step_id"])
            candidate = state.method_candidates.get(event["arguments"].get("candidate_id")) if event else None
            if decision == "reject" or candidate is None:
                if decision == "approve":
                    entry.update(applied=False, error="The recorded method for this approval was not found")
                    task["reason"] = "Approval could not be applied: recorded method not found. " + task.get("reason", "")
                else:
                    task.update(status="reviewed", reason="Rejected by host; data retained. " + task.get("reason", ""),
                                assessed_version=state.current_ref.version)
                log.append(entry)
                continue
            if candidate["kind"] == "generated":
                from .experiments import runtime_status
                runtime = runtime_status()
                if not runtime.get("available"):
                    entry.update(applied=False, error="Docker unavailable: " + runtime.get("error", ""))
                    log.append(entry)
                    continue
                state.sandbox_checked = True
            # Re-test on the current version: an earlier approval may already have changed the data.
            tool, arguments = _retest_arguments(candidate)
            trial = json.loads(executor.execute(tool, arguments, origin="host_approval"))
            if trial.get("error_kind") == "duplicate_method" and trial.get("candidate_status") == "passed":
                trial = {**trial, "success": True}  # identical method already passed on this version
            if not trial.get("success"):
                entry.update(applied=False, error=str(trial.get("error", "Trial failed on the current version")))
                task["reason"] = f"Approved, but the re-test failed on {state.current_ref.version}: {entry['error']}"
                log.append(entry)
                continue
            state.approve_all = True  # only this explicitly approved change
            try:
                applied = json.loads(executor.execute("apply_candidate", {"candidate_id": trial["candidate_id"],
                    "assessment": f"Approved by host for {task['id']} ({task['step_id']})"}, origin="host_approval"))
            finally:
                state.approve_all = False
            entry.update(applied=bool(applied.get("success")), version=state.current_ref.version,
                         changed_cells=(applied.get("effect") or {}).get("changed_cells"), error=applied.get("error"))
            if applied.get("success"):
                task.update(status="reviewed", applied_version=state.current_ref.version,
                            reason=f"Approved by host and applied as {state.current_ref.version}. " + task.get("reason", ""),
                            assessed_version=state.current_ref.version)
            else:
                task["reason"] = f"Approved, but application failed: {applied.get('error')}"
            log.append(entry)
        decided = {e["step_id"] for e in log if e["decision"] == "reject" or e.get("applied")}
        state.pending_approvals = [p for p in state.pending_approvals
                                   if not any(f"(step_id={step_id})" in p for step_id in decided)]
    finally:
        state.focused_cleaning = focused
        state.validation = None
    state.host_decisions.extend(log)
    return log
