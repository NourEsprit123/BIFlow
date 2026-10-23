import json

import pandas as pd
import streamlit as st

from components import page_header, setup
from workspace import (
    PROFILE_STATE_KEY,
    get_workspace_result,
    load_selected_dataset,
    profile_dataset_for_workspace,
    profiling_execution_status,
)

setup("Agent 1 · Profiling", hub="Agent 1 · Data Engineering")
page_header(
    "Agent 1 · Data Profiling",
    "Profile the selected dataset and inspect LLM reasoning and sandbox checks.",
    crumbs="Agent 1 · Data Engineering › **Profiling**",
)

path, frame = load_selected_dataset()
if path is None or frame is None:
    st.warning("Upload a dataset before running Data Profiling.")
    st.stop()

st.caption(f"Dataset: {path.name} · {len(frame):,} rows × {len(frame.columns)} columns")
if st.button("Run Data Profiling Agent", type="primary", use_container_width=True):
    profile_dataset_for_workspace(path, refresh=True)
    st.rerun()

result = get_workspace_result(PROFILE_STATE_KEY, path)
if result is None:
    st.info("No current profile. Run the agent to inspect this dataset.")
    st.stop()

used_llm, message = profiling_execution_status(result)
(st.info if used_llm else st.warning)(message)
profile = result["profile"]
health = result["health"]
metrics = st.columns(4)
metrics[0].metric("Rows", f"{profile['rows']:,}")
metrics[1].metric("Columns", profile["columns"])
metrics[2].metric("Health score", f"{health['overall_health_score']}%")
metrics[3].metric("Duplicate rows", health["duplicate_info"]["count"])

report = result["profiling_report"]
st.subheader("Agent summary")
st.write(report.get("agent_summary") or "No narrative summary was produced.")
profiles = report.get("column_profiles", {})
if profiles:
    column_rows = [
        {
            "Column": name,
            "Type": details.get("dtype", ""),
            "Role": details.get("inferred_role", ""),
            "Missing": details.get("missing_count", 0),
            "Unique": details.get("unique_count", 0),
            "Issues": len(details.get("issues", [])),
            "Reasoning": details.get("agent_reasoning", ""),
        }
        for name, details in profiles.items()
    ]
    st.subheader("Column profiles")
    st.dataframe(pd.DataFrame(column_rows), hide_index=True, use_container_width=True)

with st.expander("Profiling report and sandbox evidence"):
    st.json(report)

st.download_button(
    "Download ProfilingReport",
    data=json.dumps(report, indent=2, default=str).encode("utf-8"),
    file_name=f"{path.stem}_profiling_report.json",
    mime="application/json",
)
