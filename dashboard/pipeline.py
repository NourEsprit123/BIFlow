"""Pipeline availability and dataset progress, shared by the workspace UI."""
from html import escape

AGENTS = [
    ("orchestrator", "Orchestrator", "⌘", False),
    ("profiler", "Data Profiling", "⌕", True),
    ("cleaner", "Data Cleaning", "✦", True),
    ("etl", "ETL / Engineering", "⇄", True),
    ("semantic", "Semantic & KPI", "∑", False),
    ("analyst", "BI Analyst", "↗", False),
    ("dashboard", "Dashboard", "▥", False),
    ("xai", "Auditor / XAI", "◇", False),
]


def pipeline_state(profile=None, cleaning=None, running=None):
    current = running or ("cleaner" if profile or cleaning else "profiler")
    validated = bool(cleaning and cleaning.validation.all_passed)
    result = []
    for key, label, icon, available in AGENTS:
        state, detail = "locked", "Team integration pending"
        if available:
            state, detail = "ready", "Ready"
            if key == "etl":
                detail = "Handled by Cleaning Agent"
            if key == "profiler" and (profile or cleaning):
                fallback = (profile or {}).get("profiling_report", {}).get("metadata", {}).get("llm_status") in {"fallback", "mixed"}
                state, detail = "complete", "Fallback report" if fallback else "Profile ready" if profile else "Profile supplied"
            if key == "cleaner" and cleaning:
                state, detail = ("complete", "Validated") if validated else ("review", "Needs review")
            if key == current and not validated:
                state = "review" if key == "cleaner" and cleaning and not running else "current"
            if key == running:
                state, detail = "current", "Running"
            if key == "etl" and cleaning:
                state, detail = (("complete", "Shared run validated") if validated
                                 else ("review", "Shared run needs review"))
            if key == "etl" and running == "cleaner":
                state, detail = "current", "Running with Cleaning Agent"
        result.append({"key": key, "label": label, "icon": icon, "available": available,
                       "state": state, "detail": detail, "current": key == current})
    if running:
        summary = next(a["label"] for a in result if a["key"] == running) + " · running"
    elif validated:
        summary = "Cleaning & ETL validated · awaiting Semantic & KPI integration"
    elif cleaning:
        summary = "Data Cleaning · review required"
    else:
        summary = "Data Cleaning · ready" if profile else "Data Profiling · ready"
    return result, summary


def pipeline_html(profile=None, cleaning=None, running=None):
    stages, summary = pipeline_state(profile, cleaning, running)
    nodes = []
    for number, stage in enumerate(stages, 1):
        current = ' aria-current="step"' if stage["current"] else ""
        label = escape(stage["label"])
        lock = '<span class="bf-node-lock" aria-label="Locked">🔒</span>' if not stage["available"] else ""
        nodes.append(f'<li class="bf-stage is-{stage["state"]}"{current} title="{escape(stage["detail"])}">'
                     f'<span class="bf-node"><span aria-hidden="true">{stage["icon"]}</span>{lock}</span>'
                     f'<b>{label}</b><small>{escape(stage["detail"])}</small></li>')
    return ('<section class="bf-pipeline"><div class="bf-pipeline-heading"><span>BI PIPELINE</span>'
            f'<b>{escape(summary)}</b></div><div class="bf-pipeline-scroll">'
            '<ol class="bf-pipeline-track" aria-label="BIFlow agent pipeline">' + "".join(nodes) + '</ol></div></section>')
