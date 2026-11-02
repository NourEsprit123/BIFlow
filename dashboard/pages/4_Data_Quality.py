from dashboard.cleaning_review import render_cleaning_result, run_cleaning_with_progress, render_experiment_runtime, render_cleaning_limits
import pandas as pd
import streamlit as st

from components import setup, page_header
from workspace import (
    CLEANING_STATE_KEY,
    PROFILE_STATE_KEY,
    cross_column_issues,
    get_workspace_result,
    load_selected_dataset,
    profile_dataset_for_workspace,
    profiling_execution_status,
    quality_summary,
)

setup("Data Quality")
page_header(
    "Data Quality",
    "Run measurable quality checks against the selected dataset and review cleaning results.",
    "Workspace › **Data Quality**",
)

if st.session_state.pop("cleaning_just_finished", False):
    st.toast("Cleaning finished. Here is what changed and what needs you.", icon="✅")


def remember_experiment_preference():
    st.session_state["prefer_generated_methods"] = st.session_state["experiment_mode_widget"]


path, frame = load_selected_dataset()
if path is None or frame is None:
    st.warning("Upload a dataset before running data quality checks.")
    st.stop()

st.caption(f"Dataset: {path.name} · {len(frame):,} rows × {len(frame.columns)} columns")
run_col, clean_col = st.columns(2)
with run_col:
    if st.button("Run quality audit", type="primary", width="stretch"):
        result = profile_dataset_for_workspace(path)
        st.success(
            f"Profiling and quality audit finished. Report created for "
            f"{result['profile']['rows']:,} rows."
        )
        used_llm, message = profiling_execution_status(result)
        (st.info if used_llm else st.warning)(message)
with clean_col:
    if st.button("Run safe cleaning", width="stretch"):
        cleaning = run_cleaning_with_progress(path)
        summary = (
            f"Cleaning finished in {cleaning.final_dataset.version}; "
            f"{len(cleaning.change_log.successful_ops())} changes applied in "
            f"{cleaning.metadata.get('mode', 'unknown')} mode to a working copy; "
            f"validation {cleaning.validation.status.value}."
        )
        if (
            cleaning.metadata.get("mode") == "llm"
            and not cleaning.unresolved_issues
            and cleaning.validation.status.value == "passed"
        ):
            st.success(summary)
        elif cleaning.metadata.get("mode") == "llm":
            st.warning(
                f"{summary} {len(cleaning.unresolved_issues)} unresolved issue(s); "
                f"validation {cleaning.validation.status.value}."
            )
        else:
            st.warning(summary + " Start Ollama to enable local tool-calling.")

cleaning = get_workspace_result(CLEANING_STATE_KEY, path)
run_tab, source_tab, settings_tab = st.tabs(["Cleaning run", "Source file quality", "Run settings"])

with settings_tab:
    st.checkbox("Encourage sandbox method experimentation", value=st.session_state.get("prefer_generated_methods", False),
                key="experiment_mode_widget", on_change=remember_experiment_preference,
                help="Builtin cleaning operations are always preferred. Check this to also encourage the LLM to try generated methods where they add value.")
    render_cleaning_limits()
    render_experiment_runtime()

with run_tab:
    if cleaning:
        render_cleaning_result(cleaning, key="quality_cleaning_trace")
    else:
        st.info("Run safe cleaning to see what was fixed, what needs your approval and the full trace here.")

with source_tab:
    health = quality_summary(frame)
    missing = health["missing_info"]
    duplicates = health["duplicate_info"]
    issues = health["type_issues"]
    cols = st.columns(4)
    cols[0].metric("Health score", f"{health['overall_health_score']}%")
    cols[1].metric("Missing values", int(missing["total_missing_cells"]))
    cols[2].metric("Duplicate rows", int(duplicates["count"]))
    cols[3].metric("Type issues", len(issues))

    dimensions = pd.DataFrame(
        [
            {"Dimension": "Completeness", "Score": health["completeness"]},
            {"Dimension": "Validity", "Score": health["validity"]},
            {"Dimension": "Uniqueness", "Score": health["uniqueness"]},
            {"Dimension": "Consistency", "Score": health["consistency"]},
        ]
    )
    st.subheader("Quality dimensions")
    st.bar_chart(dimensions.set_index("Dimension"))

    issue_rows = []
    for column, count in missing["columns"].items():
        if count:
            issue_rows.append({
                "Column": str(column),
                "Issue": "Missing values",
                "Count": int(count),
                "Recommendation": "Review the profiling report and cleaning plan.",
            })
    for column, details in issues.items():
        issue_rows.append({
            "Column": str(column),
            "Issue": details.get("issue", "Type mismatch") if isinstance(details, dict) else "Type mismatch",
            "Count": details.get("count", "—") if isinstance(details, dict) else "—",
            "Recommendation": "Review the profiling report and cleaning plan.",
        })
    for item in cross_column_issues(frame):
        issue_rows.append({
            "Column": ", ".join(map(str, item.get("columns", []))) or "Multiple columns",
            "Issue": item.get("issue", "Cross-column check"),
            "Count": item.get("count", "—"),
            "Recommendation": item.get("recommendation", "Investigate related values."),
        })

    st.subheader("Detected issues")
    if issue_rows:
        st.dataframe(pd.DataFrame(issue_rows).astype({"Count": "string"}), hide_index=True, width="stretch")
    else:
        st.success("No missing-value, type, duplicate-row, or supported cross-column issues detected.")

    profile_result = get_workspace_result(PROFILE_STATE_KEY, path)
    if profile_result:
        report = profile_result["profiling_report"]
        with st.expander("Profiling agent findings"):
            st.write(report.get("agent_summary", "No narrative summary was produced."))
            st.json(report.get("recommended_cleaning_order", []))
