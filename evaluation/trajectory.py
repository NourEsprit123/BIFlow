"""Process metrics computed from a run's saved trace; no model calls."""
from __future__ import annotations

from collections import Counter

TEST_TOOLS = {"test_builtin", "test_generated"}
# Turns an efficient agent needs per task category: inspect, then one repair or assessment.
REFERENCE_TURNS = {"types": 2, "missing": 2, "formatting": 2, "duplicates": 2, "outliers": 2, "domain": 2}


def _invalid(event) -> bool:
    result = event["result"]
    return (result.get("error_kind") == "invalid_tool_arguments"
            or "Invalid builtin parameters" in str(result.get("original_error") or result.get("error") or ""))


def task_metrics(task, events) -> dict:
    own = [e for e in events if e.get("task_id") == task["id"]]
    model = [e for e in own if e["origin"] == "model"]
    tests = [e for e in model if e["tool"] in TEST_TOOLS]
    first_test = tests[0] if tests else None
    first_change = next((i for i, e in enumerate(model) if e["tool"] in TEST_TOOLS | {"flag_for_review", "complete_task"}), None)
    turns, reference = task.get("turns", 0), REFERENCE_TURNS.get(task["category"])
    return {
        "task": task["id"], "category": task["category"], "columns": task["columns"], "status": task["status"],
        "drop_reason": task.get("drop_reason"), "turns": turns,
        "efficiency": round(min(1.0, reference / turns), 3) if turns and reference else None,
        "actions": len(model), "invalid_requests": sum(_invalid(e) for e in own),
        "stalled_inspections": sum(e["result"].get("error_kind") == "inspection_no_progress" for e in own),
        "repeated_methods": sum(e["result"].get("error_kind") == "duplicate_method" for e in own),
        "corrections": sum(e["origin"] in {"request_correction", "self_correction"} for e in own),
        "groq_generations": sum(e["origin"] == "groq_generation" for e in own),
        "builtin_first": None if not first_test else first_test["tool"] == "test_builtin",
        "used_generated": any(e["tool"] == "test_generated" for e in own),
        "inspected_first": None if first_change is None else any(e["tool"] == "inspect_data" for e in model[:first_change]),
    }


def run_metrics(result) -> dict:
    meta = result.metadata
    events = meta.get("events", [])
    tasks = [task_metrics(t, events) for t in meta.get("cleaning_tasks", []) if t.get("turns") or
             any(e.get("task_id") == t["id"] for e in events)]
    steps = meta.get("step_log", [])
    model_steps = [s for s in steps if s.get("timing")]
    tests = sum(1 for e in events if e["tool"] in TEST_TOOLS)

    def rate(values):
        values = [v for v in values if v is not None]
        return round(sum(values) / len(values), 3) if values else None
    return {
        "stop_reason": meta.get("stop_reason"), "turns": meta.get("turns_used"),
        "elapsed_seconds": round(meta.get("elapsed_seconds", 0), 1),
        "model_seconds": round(sum(s["timing"].get("request_seconds") or 0 for s in model_steps), 1),
        "prompt_tokens": sum((s.get("usage") or {}).get("prompt_tokens") or 0 for s in model_steps),
        "completion_tokens": sum((s.get("usage") or {}).get("completion_tokens") or 0 for s in model_steps),
        "context_sheds": sum("context_budget" in s for s in steps),
        "invalid_request_rate": round(sum(_invalid(e) for e in events) / tests, 3) if tests else None,
        "builtin_first_rate": rate([t["builtin_first"] for t in tasks]),
        "inspect_first_rate": rate([t["inspected_first"] for t in tasks]),
        "mean_task_efficiency": rate([t["efficiency"] for t in tasks]),
        "groq_requests": sum(1 for g in meta.get("expert_generations", {}).values() if g.get("request_sent")),
        "drops": dict(Counter(d["reason"] for d in meta.get("task_drops", []))),
        "task_status": dict(Counter(t["status"] for t in meta.get("cleaning_tasks", []))),
        "tasks": tasks,
    }
