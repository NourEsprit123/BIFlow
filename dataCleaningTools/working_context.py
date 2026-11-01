"""Per-run progress over an independent profiling-report copy.

Completion is measured on the persisted working dataset, never inferred from a
model explanation or from a passing trial on an uncommitted copy.
"""
from __future__ import annotations

from copy import deepcopy

from .contracts import canonical_type
from .effects import present, target_matches


def refresh(state, frame=None):
    if frame is None:
        frame = state.manager.load(state.current_ref)
    version = state.current_ref.version
    previous = state.working_context.get("columns", {})
    columns = {}
    names = dict.fromkeys([*frame.columns, *state.working_report.get("column_profiles", {}),
                          *state.required_targets, *state.required_missing])
    for name in names:
        exists = name in frame
        missing = int((~present(frame[name])).sum()) if exists else None
        steps = {}
        if name in state.required_targets:
            target = state.required_targets[name]
            steps["type_conversion"] = {
                "target": canonical_type(target),
                "status": "done" if exists and target_matches(frame[name], target) else "pending",
            }
        if name in state.required_missing:
            steps["missing_values"] = {"remaining": missing,
                "status": "done" if exists and missing == 0 else "pending"}
        for kind, step in steps.items():
            if name in state.flagged:
                step.update(status="needs_review", reason=state.flagged[name])
            step["verified_version"] = version
            if step["status"] == "done":
                old = previous.get(name, {}).get("steps", {}).get(kind, {})
                step["completed_version"] = (old.get("completed_version", version)
                    if old.get("status") == "done" and old.get("target") == step.get("target") else version)
        columns[name] = {"current_dtype": str(frame[name].dtype) if exists else "absent",
                         "missing_count": missing, "steps": steps,
                         "current_examples": [str(v)[:60] for v in frame[name].dropna().head(3)] if exists else []}
    actions = []
    for event in state.events:
        result = event["result"]
        if result.get("accepted") and result.get("success") and not result.get("no_op") and event["source_version"] != event["version"]:
            candidate = state.method_candidates.get(event["arguments"].get("candidate_id"), {})
            actions.append({"event_id": event["event_id"], "version": event["version"],
                "operation": candidate.get("operation", "generated_transform" if candidate.get("code") else event["tool"]),
                "columns": candidate.get("columns") or event["arguments"].get("columns") or
                           ([event["arguments"]["column"]] if "column" in event["arguments"] else []),
                "explanation": candidate.get("hypothesis") or event.get("explanation") or result.get("rationale", "")})
    state.working_context = {"version": version, "columns": columns,
                             "completed_actions": actions, "flagged": dict(state.flagged)}
    from .cleaning_tasks import refresh as refresh_tasks
    refresh_tasks(state)


def initialize(state, report):
    state.working_report = report.model_dump(mode="json")
    refresh(state)


def model_context(state, columns=None):
    """Project the measured memory; callers refresh it before preparing a request."""
    from .cleaning_tasks import informational
    selected = state.working_context.get("columns", {})
    if columns is not None:
        selected = {name: current for name, current in selected.items() if name in columns}
    columns = {}
    for name, current in selected.items():
        original = state.working_report.get("column_profiles", {}).get(name, {})
        observations = []
        for issue in original.get("issues", []):
            if informational(issue):
                continue
            kind = {"type_mismatch": "type_conversion", "missing_values": "missing_values"}.get(issue["issue_id"])
            if kind and current["steps"].get(kind, {}).get("status") == "done":
                continue
            observations.append({"description": issue.get("description", "")[:160],
                                 "status": current["steps"].get(kind, {}).get("status", "advisory")})
        columns[name] = {**deepcopy(current), "observations": observations}
        if any(step["status"] == "pending" for step in current["steps"].values()):
            if original.get("imputation_strategy"):
                columns[name]["suggested_imputation"] = original["imputation_strategy"]
            elif name in state.working_report.get("imputation_plan", {}):
                columns[name]["suggested_imputation"] = deepcopy(state.working_report["imputation_plan"][name])
    return {"dataset": state.working_report.get("dataset_ref", {}).get("file_name"),
            "version": state.current_ref.version, "columns": columns,
            "completed_actions": [{k: deepcopy(v) for k, v in action.items() if k != "explanation"}
                                  for action in state.working_context.get("completed_actions", [])],
            "instruction": "Steps marked done are verified on the current working data. Do not repeat them; address pending steps or explain review blockers. Advisory observations are not automatically resolved."}
