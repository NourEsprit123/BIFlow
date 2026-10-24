from dashboard.cleaning_review import render_cleaning_result
import json
from datetime import datetime, timezone

import streamlit as st

from components import setup, page_header
from workspace import (
    CLEANING_STATE_KEY,
    PROFILE_STATE_KEY,
    get_workspace_result,
    load_selected_dataset,
    profile_dataset_for_workspace,
    profiling_execution_status,
)

setup("Agent Operations")
page_header(
    "Agent Operations",
    "View the local agent actions actually completed in this workspace session.",
    crumbs="Workspace › **Agent Ops**",
)

path, frame = load_selected_dataset()
if path is None or frame is None:
    st.warning("Upload a dataset to run and monitor the agents.")
    st.stop()

profile_result = get_workspace_result(PROFILE_STATE_KEY, path)
cleaning_result = get_workspace_result(CLEANING_STATE_KEY, path)
current_profile = profile_result is not None

if st.button("Run profiling health check", type="primary"):
    profile_dataset_for_workspace(path, refresh=True)
    st.rerun()

agents = [
    {
        "Agent": "Data Profiling Agent",
        "Status": (
            "Completed" if profiling_execution_status(profile_result)[0] else "Fallback"
        ) if current_profile else "Ready",
        "Last result": (
            f"{profile_result['profile']['rows']:,} rows · "
            f"{profiling_execution_status(profile_result)[1]}"
            if current_profile else "No run in this session"
        ),
    },
    {
        "Agent": "Data Cleaning Agent",
        "Status": (
            "Completed"
            if cleaning_result.metadata.get("mode") == "llm"
            and not cleaning_result.unresolved_issues
            and cleaning_result.validation.status.value == "passed"
            else "Needs review"
            if cleaning_result.metadata.get("mode") == "llm"
            else "Fallback"
        ) if cleaning_result else "Ready",
        "Last result": (
            f"{len(cleaning_result.change_log.successful_ops())} changes; "
            f"validation {cleaning_result.validation.status.value}; "
            f"{cleaning_result.metadata.get('mode', 'unknown')} mode"
            if cleaning_result else "No run in this session"
        ),
    },
]

st.subheader(f"Agent status · {path.name}")
st.dataframe(agents, hide_index=True, use_container_width=True)

telemetry = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "dataset": str(path),
    "agents": agents,
}
with st.expander("Session telemetry"):
    st.json(telemetry)

st.download_button(
    "Export session telemetry",
    data=json.dumps(telemetry, indent=2),
    file_name="biflow_session_telemetry.json",
    mime="application/json",
)
st.caption(
    "This build runs agents on demand in the Streamlit process. There is no persistent "
    "agent pool to restart and no 15-second telemetry stream configured."
)

if cleaning_result:
    render_cleaning_result(cleaning_result, key="ops_cleaning_trace")
