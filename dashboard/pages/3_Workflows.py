from dashboard.cleaning_review import render_cleaning_result, run_cleaning_with_progress
from pathlib import Path

import streamlit as st

from components import setup, page_header
from workspace import (
    CLEANING_STATE_KEY,
    PROFILE_STATE_KEY,
    load_selected_dataset,
    profile_dataset_for_workspace,
    load_dataset,
    profiling_report_json,
    get_workspace_result,
    profiling_execution_status,
)

setup("Workflows")
page_header(
    "Analysis Workflow",
    "Run the integrated profiling and cleaning agents. Later BI stages are locked until team integration.",
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
    "KPI analysis": False,
    "Audit report verification": False,
}
locked_tasks = {"KPI analysis", "Audit report verification"}
selected = {}
for index, (task, default) in enumerate(task_options.items()):
    key = f"workflow_task_{index}"
    if task in locked_tasks:
        st.session_state[key] = False
    value = st.checkbox(task + (" · locked" if task in locked_tasks else ""),
                        value=default, key=key, disabled=task in locked_tasks)
    selected[task] = value and task not in locked_tasks
st.caption("BI Analysis and Auditor / XAI are being developed by the team.")

explain = st.checkbox("Include agent reasoning in the run summary", value=True, key="workflow_include_reasoning")

def restore_template():
    template = st.session_state["workflow_template"]
    for index, name in enumerate(task_options):
        st.session_state[f"workflow_task_{index}"] = name in template["tasks"] and name not in locked_tasks
    st.session_state["workflow_include_reasoning"] = template["include_reasoning"]


saved_template = st.session_state.get("workflow_template")
if saved_template:
    st.caption(f"Saved template: {saved_template['name']} · {len(saved_template['tasks'])} tasks")
    st.button("Load saved template", on_click=restore_template)

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
        cleaning_result = None
        profile_result = get_workspace_result(PROFILE_STATE_KEY, path)
        if (
            selected["Data profiling"]
            or selected["Data quality audit"]
            or selected["Audit report verification"]
            or (selected["Data cleaning (versioned copy)"] and profile_result is None)
        ):
            st.write("Data Profiling Agent: inspecting the selected dataset...")
            profile_result = profile_dataset_for_workspace(path, refresh=True)
            used_llm, message = profiling_execution_status(profile_result)
            (st.write if used_llm else st.warning)(message)

        if selected["Data cleaning (versioned copy)"]:
            st.write("Data Cleaning Agent: creating a versioned working copy...")
            cleaning_result = run_cleaning_with_progress(path)
            st.write(
                f"Cleaning ran in {cleaning_result.metadata.get('mode', 'unknown')} "
                f"mode with {len(cleaning_result.change_log.successful_ops())} "
                "successful transformation(s)."
            )

        if explain and profile_result:
            summary = profile_result["profiling_report"].get("agent_summary")
            if summary:
                st.write(summary)
        needs_review = cleaning_result is not None and not cleaning_result.validation.all_passed
        status.update(label="Workflow needs review" if needs_review else "Workflow finished",
                      state="error" if needs_review else "complete")

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
    render_cleaning_result(cleaning_result, key="workflow_cleaning_trace")
    cleaned = load_dataset(cleaning_result.final_dataset.path)
    st.download_button(
        "Download cleaned CSV" if cleaning_result.validation.all_passed else "Download working CSV (review required)",
        data=cleaned.to_csv(index=False).encode("utf-8"),
        file_name=f"{path.stem}_cleaned.csv",
        mime="text/csv",
    )
