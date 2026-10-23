from datetime import datetime
from html import escape

import streamlit as st

from components import setup, page_header
from workspace import (
    CLEANING_STATE_KEY,
    PROFILE_STATE_KEY,
    get_workspace_result,
    list_datasets,
    load_selected_dataset,
    profile_dataset_for_workspace,
    profiling_execution_status,
    quality_summary,
)

setup("Overview")
user = st.session_state.get("authenticated_user", {})
first_name = escape((user.get("full_name") or "there").split()[0])
hour = datetime.now().hour
greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
page_header(f"{greeting}, {first_name}.", "Run agents against your selected dataset and review real results.")

path, frame = load_selected_dataset()
if path is None or frame is None:
    st.warning("Upload a dataset to begin.")
    st.page_link("pages/2_Datasets.py", label="Open datasets", icon="🗄")
    st.stop()

health = quality_summary(frame)
profile_result = get_workspace_result(PROFILE_STATE_KEY, path)
cleaning = get_workspace_result(CLEANING_STATE_KEY, path)
current_profile = profile_result is not None

st.info(f"Active dataset: **{path.name}** · {len(frame):,} rows × {len(frame.columns)} columns")
metrics = st.columns(4)
metrics[0].metric("Datasets available", len(list_datasets()))
metrics[1].metric("Rows", f"{len(frame):,}")
metrics[2].metric("Columns", len(frame.columns))
metrics[3].metric("Data quality", f"{health['overall_health_score']}%")

profile_col, analysis_col = st.columns(2)
with profile_col:
    if st.button("Run Data Profiling Agent", type="primary", use_container_width=True):
        result = profile_dataset_for_workspace(path, refresh=True)
        st.success(
            f"Profile completed: {result['profile']['rows']:,} rows, "
            f"{result['profile']['columns']} columns."
        )
        used_llm, message = profiling_execution_status(result)
        (st.info if used_llm else st.warning)(message)
with analysis_col:
    if st.button("Create analysis", use_container_width=True):
        st.switch_page("pages/5_BI_Analysis.py")

st.subheader("Agent activity")
agent_rows = [
    {
        "Agent": "Data Profiling Agent",
        "Status": (
            "Completed" if profiling_execution_status(profile_result)[0] else "Fallback"
        ) if current_profile else "Ready",
        "Latest work": (
            f"{profile_result['profile']['rows']:,} rows profiled · "
            f"{profiling_execution_status(profile_result)[1]}"
            if current_profile else "Run a profile to create a report"
        ),
    },
    {
        "Agent": "Data Cleaning Agent",
        "Status": (
            "Completed"
            if cleaning.metadata.get("mode") == "llm"
            and not cleaning.unresolved_issues
            and cleaning.validation.status.value == "passed"
            else "Needs review"
            if cleaning.metadata.get("mode") == "llm"
            else "Fallback"
        ) if cleaning else "Ready",
        "Latest work": (
            f"{len(cleaning.change_log.successful_ops())} changes; "
            f"{cleaning.metadata.get('mode', 'unknown')} mode; versioned copy"
            if cleaning else "No cleaning run in this session"
        ),
    },
]
st.dataframe(agent_rows, hide_index=True, use_container_width=True)

st.subheader("Selected dataset preview")
st.dataframe(frame.head(10), hide_index=True, use_container_width=True)
