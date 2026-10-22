import streamlit as st

from components import setup, page_header
from workspace import (
    CLEANING_STATE_KEY,
    PROFILE_STATE_KEY,
    load_selected_dataset,
    profile_dataset_for_workspace,
    clean_profiled_dataset,
    analyze_dataframe,
    load_dataset,
    profiling_report_json,
    get_workspace_result,
    verify_profiling_report,
)

setup("Workflows")
page_header(
    "Analysis Workflow",
    "Run the profiling, quality, cleaning, and KPI tools against the active dataset.",
    "Workspace › **Workflows**",
)

path, frame = load_selected_dataset()
if path is None or frame is None:
    st.warning("Upload a dataset before creating a workflow.")
    st.stop()

st.info(f"Active dataset: **{path.name}** · {len(frame):,} rows · {len(frame.columns)} columns")

st.subheader("Tasks")
task_options = {
    "Data profiling": True,
    "Data quality audit": True,
    "Data cleaning (versioned copy)": False,
    "KPI analysis": True,
    "Audit report verification": False,
}
selected = {
    task: st.checkbox(task, value=default, key=f"workflow_task_{index}")
    for index, (task, default) in enumerate(task_options.items())
}
explain = st.checkbox("Include agent reasoning in the run summary", value=True)

saved_template = st.session_state.get("workflow_template")
if saved_template:
    st.caption(f"Saved template: {saved_template['name']} · {len(saved_template['tasks'])} tasks")

save_col, run_col = st.columns([1, 2])
with save_col:
    if st.button("Save as template"):
        st.session_state["workflow_template"] = {
            "name": f"{path.stem} workflow",
            "tasks": [name for name, enabled in selected.items() if enabled],
            "include_reasoning": explain,
        }
        st.success("Workflow settings saved for this session.")
with run_col:
    run_clicked = st.button(
        "Run BIFlow Pipeline",
        type="primary",
        use_container_width=True,
        disabled=not any(selected.values()),
    )

if run_clicked:
    with st.status("Running selected workflow tasks...", expanded=True) as status:
        profile_result = get_workspace_result(PROFILE_STATE_KEY, path)
        if (
            selected["Data profiling"]
            or selected["Data quality audit"]
            or selected["Audit report verification"]
            or (selected["Data cleaning (versioned copy)"] and profile_result is None)
        ):
            st.write("Data Profiling Agent: inspecting the selected dataset...")
            profile_result = profile_dataset_for_workspace(path, refresh=True)
            st.write("Profiling and deterministic quality checks complete.")

        if selected["Data cleaning (versioned copy)"]:
            st.write("Data Cleaning Agent: creating a versioned working copy...")
            cleaning_result = clean_profiled_dataset(path)
            st.write(
                f"Cleaning completed with {len(cleaning_result.change_log.successful_ops())} "
                "successful transformation(s)."
            )

        if selected["KPI analysis"]:
            analysis = analyze_dataframe(frame, path)
            st.write(
                f"BI Analyst: analyzed {analysis['rows']:,} rows, "
                f"{analysis['numeric_columns']} numeric columns, and "
                f"{analysis['categorical_columns']} categorical columns."
            )

        if selected["Audit report verification"]:
            if profile_result is None:
                st.warning("Run Data Profiling before verifying the audit report.")
            else:
                verification = verify_profiling_report(path, profile_result)
                if verification["verified"]:
                    st.write(f"XAI Auditor: report verified, SHA-256 {verification['sha256']}")
                else:
                    st.error(f"XAI Auditor: {verification['reason']}")

        if explain and profile_result:
            summary = profile_result["profiling_report"].get("agent_summary")
            if summary:
                st.write(summary)
        status.update(label="Workflow finished", state="complete")

profile_result = get_workspace_result(PROFILE_STATE_KEY, path)
if profile_result:
    report_bytes = profiling_report_json()
    if report_bytes is None:
        st.error("The profiling report is not available for download.")
    else:
        st.download_button(
            "Download profiling report",
            data=report_bytes,
            file_name=f"{path.stem}_profiling_report.json",
            mime="application/json",
        )

cleaning_result = get_workspace_result(CLEANING_STATE_KEY, path)
if cleaning_result:
    st.subheader("Latest cleaning run")
    st.write(
        f"{cleaning_result.final_dataset.version}: "
        f"{len(cleaning_result.change_log.successful_ops())} successful change(s); "
        f"validation {cleaning_result.validation.status.value}."
    )
    if cleaning_result.unresolved_issues:
        st.warning("Some changes require review or approval.")
        for issue in cleaning_result.unresolved_issues:
            st.write(f"- {issue}")
    cleaned = load_dataset(cleaning_result.final_dataset.path)
    st.download_button(
        "Download cleaned CSV",
        data=cleaned.to_csv(index=False).encode("utf-8"),
        file_name=f"{path.stem}_cleaned.csv",
        mime="text/csv",
    )
