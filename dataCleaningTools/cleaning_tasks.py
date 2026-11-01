"""A small, profiling-driven queue. One category and one repair at a time."""
from copy import deepcopy
import json
from pathlib import Path

CATEGORIES = (
    ("understanding", "Understand data and quality requirements"),
    ("formatting", "Correct structure and formatting"),
    ("types", "Correct data types and invalid values"),
    ("duplicates", "Investigate duplicate records"),
    ("missing", "Handle missing values"),
    ("outliers", "Investigate outliers and inconsistent records"),
    ("domain", "Apply documented domain consistency rules"),
    ("validation", "Validate and document the result"),
)
ORDER = {key: index for index, (key, _) in enumerate(CATEGORIES)}
GUIDANCE = json.loads((Path(__file__).with_name("prompts") / "categories.json").read_text(encoding="utf-8"))
# Terminal statuses set by the host; measurements never reopen them.
CLOSED = {"dropped", "blocked", "awaiting_approval"}


def informational(finding):
    # Missing severity is not proof of harmlessness. Only explicit informational
    # findings are omitted; independently required type/missing checks stay queued.
    severity = finding.get("severity")
    return isinstance(severity, str) and severity.strip().upper() in {"NONE", "INFO", "INFORMATIONAL"}


def issue_category(issue_id):
    name = issue_id.lower()
    if "missing" in name:
        return "missing"
    if "duplicate" in name:
        return "duplicates"
    if "outlier" in name:
        return "outliers"
    if any(word in name for word in ("type", "invalid", "malformed")):
        return "types"
    if any(word in name for word in ("whitespace", "format", "casing", "capital", "categor", "unit", "column_name")):
        return "formatting"
    return "domain"


def _add_task(tasks, category, columns, evidence, measured=None):
    columns = list(dict.fromkeys(columns))
    existing = next((t for t in tasks if t["category"] == category and set(t["columns"]) == set(columns)
                     and t.get("measured") == measured), None)
    if existing:
        if evidence in existing["evidence"]:
            return
        if measured == "type_conversion" and "target_type" in evidence:
            existing["evidence"] = [e for e in existing["evidence"] if "target_type" not in e]
        existing["evidence"].append(deepcopy(evidence))
        return
    number = max((int(t["id"][5:]) for t in tasks if t["id"].startswith("task-") and t["id"][5:].isdigit()), default=0) + 1
    tasks.append({"id": f"task-{number}", "category": category, "columns": columns,
                  "evidence": [deepcopy(evidence)], "measured": measured, "status": "pending"})


def _requirements(state):
    for column, target in state.required_targets.items():
        yield "types", column, {"target_type": target}, "type_conversion"
    for column in dict.fromkeys(state.required_missing):
        yield "missing", column, {"reported_missing_values": True}, "missing_values"


def _changed_since(state, columns, version):
    return any(int(a["version"][1:]) > int(version[1:]) and set(a["columns"]) & set(columns)
               for a in state.working_context.get("completed_actions", []))


def initialize(state):
    report = state.working_report
    tasks = []
    def add(category, columns, evidence, measured=None):
        _add_task(tasks, category, columns, evidence, measured)
    for category, column, evidence, measured in _requirements(state):
        add(category, [column], evidence, measured)
    for column, profile in report.get("column_profiles", {}).items():
        for issue in profile.get("issues", []):
            if informational(issue):
                continue
            category = issue_category(issue["issue_id"])
            measured = ("type_conversion" if issue["issue_id"] == "type_mismatch" and column in state.required_targets
                        else "missing_values" if issue["issue_id"] == "missing_values" and column in state.required_missing else None)
            add(category, [column], issue, measured)
    for column in report.get("outlier_columns", []):
        add("outliers", [column], {"reported_outliers": True})
    for column, mapping in report.get("etl_hints", {}).get("synonym_mappings", {}).items():
        add("formatting", [column], {"suggested_synonym_mapping": mapping,
                                    "note": "Verify shared meaning before merging labels"})
    for finding in (report.get("cross_column_issues", []) + report.get("llm_discovered_issues", [])
                    + report.get("uncertainty_flags", [])):
        finding = finding if isinstance(finding, dict) else {"description": str(finding)}
        if informational(finding):
            continue
        columns = finding.get("columns") or ([finding["column"]] if finding.get("column") else [])
        columns = [columns] if isinstance(columns, str) else columns
        add(issue_category(str(finding.get("issue_id", "domain"))), list(columns), finding)
    state.cleaning_tasks = sorted(tasks, key=lambda t: ORDER[t["category"]])
    refresh(state)


def refresh(state):
    if state.focused_cleaning:
        count = len(state.cleaning_tasks)
        for category, column, evidence, measured in _requirements(state):
            _add_task(state.cleaning_tasks, category, [column], evidence, measured)
        if len(state.cleaning_tasks) != count:
            state.cleaning_tasks.sort(key=lambda task: ORDER[task["category"]])
            state.validation = None
    for task in state.cleaning_tasks:
        if task["status"] in CLOSED:
            continue
        previous_status = task["status"]
        measured = task.get("measured")
        if measured:
            step = state.working_context.get("columns", {}).get(task["columns"][0], {}).get("steps", {}).get(measured, {})
            task["status"] = step.get("status", "not_required")
            task["verified_version"] = state.current_ref.version
            task.pop("reason", None)
            if step.get("reason"):
                task["reason"] = step["reason"]
        elif task["columns"] and any(c in state.flagged for c in task["columns"]):
            task.update(status="needs_review", reason="; ".join(state.flagged[c] for c in task["columns"] if c in state.flagged))
        elif task["status"] == "reviewed" and _changed_since(state, task["columns"], task.get("assessed_version", "V0")):
            task.update(status="pending", reopened_version=state.current_ref.version)
            task.pop("reason", None)
        if task["status"] != previous_status:
            state.validation = None


def active(state):
    return next((t for t in state.cleaning_tasks if t["status"] == "pending"), None)


def closed(state, task):
    """True once the run stopped or the given task left pending (e.g. it was dropped mid-pipeline)."""
    return state.finished or bool(task and task["status"] != "pending")


def failed_attempts(state, task):
    """Distinct methods the model chose for this task that ran and failed."""
    return [e for e in state.events if e.get("task_id") == task["id"] and e["origin"] == "model"
            and e["tool"] in {"test_builtin", "test_generated"} and e["result"].get("candidate_id")
            and not e["result"].get("success") and e["result"].get("error_kind") != "duplicate_method"]


def drop(state, task, reason, detail):
    """Give up on a task without certifying it, and block later tasks on its columns."""
    attempts = [{"event_id": e["event_id"], "tool": e["tool"], "error": str(e["result"].get("error", ""))[:300]}
                for e in failed_attempts(state, task)]
    task.update(status="dropped", drop_reason=reason, reason=f"Dropped ({reason}): {detail}",
                failed_attempts=attempts, assessed_version=state.current_ref.version)
    closed = [task]
    for other in state.cleaning_tasks:
        if other["status"] == "pending" and set(other["columns"]) & set(task["columns"]):
            other.update(status="blocked", blocked_by=task["id"],
                         reason=f"Blocked: {task['id']} on the same columns was dropped ({reason})")
            closed.append(other)
    # Measured obligations on these columns can no longer be met this run; freeze them for review.
    for item in closed:
        if item.get("measured"):
            state.flagged.update({c: item["reason"] for c in item["columns"] if c not in state.flagged})
    state.validation = None
    state.task_drops.append({"task_id": task["id"], "reason": reason, "detail": detail,
                             "blocked": [t["id"] for t in closed[1:]], "turn": state.current_turn})
    return task


def drop_unrunnable(state):
    """Tasks committed to generated code cannot proceed once Docker is known to be unavailable."""
    while state.sandbox_error and (task := active(state)) and task.get("generated_required"):
        drop(state, task, "sandbox_unavailable", state.sandbox_error)


def enforce_budget(state, task_id):
    """After a turn: charge it to the task it started on, and drop that task once over budget."""
    task = next((t for t in state.cleaning_tasks if t["id"] == task_id), None)
    if not task:
        return None
    task["turns"] = task.get("turns", 0) + 1
    if task["status"] != "pending":
        return None
    if task["turns"] >= state.max_task_turns:
        return drop(state, task, "turn_budget", f"no resolution after {task['turns']} model turns")
    failures = len(failed_attempts(state, task))
    if failures >= state.max_task_failures:
        return drop(state, task, "attempt_budget", f"{failures} distinct methods failed")
    return None


def context(state):
    task = active(state)
    category = task["category"] if task else "validation"
    return {"task": deepcopy(task), "category": category,
            "guidance": GUIDANCE[category],
            "remaining_tasks": sum(t["status"] == "pending" for t in state.cleaning_tasks)}


def summary(state):
    categories = []
    for key, title in CATEGORIES:
        tasks = [t for t in state.cleaning_tasks if t["category"] == key]
        status = ("pending" if any(t["status"] == "pending" for t in tasks) else
                  "dropped" if any(t["status"] == "dropped" for t in tasks) else
                  "blocked" if any(t["status"] == "blocked" for t in tasks) else
                  "awaiting_approval" if any(t["status"] == "awaiting_approval" for t in tasks) else
                  "needs_review" if any(t["status"] == "needs_review" for t in tasks) else
                  "not_required" if tasks and all(t["status"] == "not_required" for t in tasks) else
                  "done" if tasks else "no_reported_findings")
        if key == "understanding":
            status = "consumed_profiling_report"
        if key == "validation":
            status = state.validation.status.value if state.validation else "pending"
        categories.append({"category": key, "title": title, "status": status, "tasks": len(tasks)})
    return categories


def model_view(state, executor):
    from .working_context import refresh as refresh_memory, model_context
    from .repair_history import model_history
    from .value_interpretation import plans
    frame = state.manager.load(state.current_ref)
    refresh_memory(state, frame)
    focus = context(state)
    task = focus["task"] or {}
    columns = task.get("columns", [])
    view = model_context(state, columns)
    for c, current in view["columns"].items():
        profile = state.working_report.get("column_profiles", {}).get(c, {})
        current["profiling_interpretation"] = {k: str(profile[k])[:400] for k in
            ("inferred_role", "business_interpretation", "uncertainty") if profile.get(k)}
        current["steps"] = {k: v for k, v in current["steps"].items() if k == task.get("measured")}
        # Other category findings and imputation suggestions stay in the audit.
        current["observations"] = task.get("evidence", [])
        if task.get("category") != "missing":
            current.pop("suggested_imputation", None)
    view["completed_actions"] = view["completed_actions"][-3:]
    progress = executor.progress(frame)
    if task:
        progress = {k: ({c: v for c, v in value.items() if c in columns} if isinstance(value, dict) else value)
                    for k, value in progress.items()}
        if task["category"] != "missing":
            progress.pop("pending_missing", None)
        if task["category"] not in {"types", "missing"}:
            progress.pop("pending_types", None)
    return {"cleaning_focus": focus, "working_context": view, "outstanding": progress,
            "investigation_progress": state.inspection_progress.get(f"{state.current_ref.version}:{task.get('id')}", {}),
            "value_interpretation": (plans(state, columns, frame=frame) if task.get("category") in {"types", "missing"} else
                {"read_only": True, "instruction": "No type conversion is requested for this task. Use the category's measurements; do not normalize or reinterpret values merely because they are numeric."}),
            "repair_history": [h for h in model_history(state) if set(h.get("columns") or []) & set(columns)]}


def request_guide(state, base):
    """Use exact task names and keep advisory decisions free of parser examples."""
    task = active(state)
    if not task:
        return 'Call finish with summary and optional unresolved list. Do not inspect or modify completed tasks.'
    columns = task["columns"]
    anchor = columns[0] if columns else ""
    if task["category"] in {"types", "missing"}:
        return f"Active task: {task['id']}. Exact columns: {json.dumps(columns)}. " + base.replace("<column>", json.dumps(anchor)[1:-1])
    inspect_example = {"name": "inspect_data", "arguments": {"reason": "Measure evidence for this finding",
        "view": "schema" if not columns else "distribution" if task["category"] == "outliers" else "column"}}
    if columns:
        inspect_example["arguments"]["column"] = anchor
    complete_example = {"name": "complete_task", "arguments": {"task_id": task["id"], "disposition": "reviewed",
        "reason": "Explain what observed evidence supports retaining the data or the validated repair"}}
    return (f"Active category: {task['category']}. Exact columns: {json.dumps(columns)}. "
        "Return one name/arguments tool call with no extra fields. Do not redo completed type conversions. "
        "Inspect evidence, then retain data with complete_task, test a justified repair, or complete_task with disposition=needs_review and the specific missing decision. "
        "For further inspections, explain the remaining question and expected evidence in reason; repeated/invalid requests count as stalls. "
        "values shows frequent examples; distribution shows actual min/max, signs and IQR counts; extremes and filtered show targeted examples. "
        "Displayed-example coverage is not missingness. Thresholds are not observed values. "
        f"Examples using your actual task: {json.dumps(inspect_example)} ; {json.dumps(complete_example)}")


def complete(executor, arguments):
    state = executor.state
    task = active(state)
    if not task or task["id"] != arguments["task_id"]:
        raise ValueError("Complete only the current task; read cleaning_focus for its ID")
    if task.get("measured"):
        raise ValueError("This task advances only after persisted dataset checks pass; repair it or flag_for_review")
    evidence = [e for e in state.events if e.get("task_id") == task["id"]
                and (e["result"].get("success", True) or e["result"].get("cached")) and (e["tool"] == "inspect_data"
                or (e["tool"] == "apply_candidate" and e["result"].get("success")))
                and not _changed_since(state, task["columns"], e["version"])]
    if arguments["disposition"] == "reviewed" and not evidence:
        raise ValueError("Inspect this task or apply a validated repair before recording its assessment")
    task.update(status=arguments["disposition"], reason=arguments["reason"],
                assessed_version=state.current_ref.version)
    state.validation = None
    return {"success": True, "task": deepcopy(task), "message": "Assessment recorded; this is not proof of business correctness."}


def check_scope(state, name, arguments):
    """Scope model actions, including repaired code and automatic application."""
    task = active(state)
    if not task:
        if name in {"test_builtin", "test_generated", "apply_candidate"}:
            raise ValueError("No pending cleaning task; finish with independent validation")
        return
    columns = arguments.get("columns", [])
    if name == "apply_candidate":
        columns = state.method_candidates.get(arguments.get("candidate_id"), {}).get("columns", [])
    op = arguments.get("operation") if name == "test_builtin" else None
    if name in {"test_builtin", "test_generated", "apply_candidate", "flag_for_review"}:
        # A dataset-level duplicates finding may name no columns; its key is the model's choice.
        dataset_level = op == "remove_duplicates" and not task["columns"]
        if not columns or not (dataset_level or set(columns).issubset(task["columns"])):
            raise ValueError("Work only on the current task's columns; do not combine unrelated repairs")
    if name == "test_builtin" and task.get("generated_required"):
        raise ValueError("This task requires test_generated; custom code was selected for it")
    if op == "handle_missing_values" and task["category"] != "missing":
        raise ValueError("Handle missing values in its own task after conversion, not in this repair")
    if op == "remove_duplicates" and task["category"] not in {"duplicates", "domain"}:
        raise ValueError("Remove duplicates only in a duplicates task")
    if op == "handle_outliers" and task["category"] not in {"outliers", "domain"}:
        raise ValueError("Handle outliers only in an outliers task, after inspecting the distribution")
    from .workflow import CATEGORY_OPERATIONS
    allowed = CATEGORY_OPERATIONS.get(task["category"])
    if op and allowed and op not in allowed:
        raise ValueError(f"{op} is not available for this {task['category']} task; choose one of {list(allowed)}")
    if name == "inspect_data" and task["columns"]:
        selected = set(arguments.get("subset", [])) | ({arguments["column"]} if arguments.get("column") else set())
        if not selected.issubset(task["columns"]):
            raise ValueError("Inspect the current task's columns; other tasks have separate turns")
