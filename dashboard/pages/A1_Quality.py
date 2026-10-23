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

setup("Agent 1 · Quality Check", hub="Agent 1 · Data Engineering")
page_header(
    "Agent 1 · Quality Check",
    "Review deterministic quality evidence produced by the Data Profiling Agent.",
    crumbs="Agent 1 · Data Engineering › **Quality Check**",
)

path, frame = load_selected_dataset()
if path is None or frame is None:
    st.warning("Upload a dataset before running a quality check.")
    st.stop()

st.caption(f"Dataset: {path.name} · {len(frame):,} rows × {len(frame.columns)} columns")
if st.button("Run Agent 1 quality check", type="primary", use_container_width=True):
    profile_dataset_for_workspace(path, refresh=True)
    st.rerun()

result = get_workspace_result(PROFILE_STATE_KEY, path)
if result is None:
    st.info("No current quality report. Run Agent 1 to profile and audit this dataset.")
    st.stop()

used_llm, message = profiling_execution_status(result)
(st.info if used_llm else st.warning)(message)
health = result["health"]
profile = result["profile"]
metrics = st.columns(5)
metrics[0].metric("Health score", f"{health['overall_health_score']}%")
metrics[1].metric("Missing cells", health["missing_info"]["total_missing_cells"])
metrics[2].metric("Duplicate rows", health["duplicate_info"]["count"])
metrics[3].metric("Type issues", len(health["type_issues"]))
metrics[4].metric("Cross-column issues", len(result["profiling_report"]["cross_column_issues"]))

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

findings = []
for column, count in health["missing_info"]["columns"].items():
    if count:
        findings.append(
            {
                "Check": "Missing values",
                "Columns": str(column),
                "Findings": str(count),
                "Details": f"{count} missing value(s).",
            }
        )
for column, details in health["type_issues"].items():
    findings.append(
        {
            "Check": "Type consistency",
            "Columns": str(column),
            "Findings": str(details.get("detected", details.get("issue", "Type issue"))),
            "Details": str(details.get("recommendation", "")),
        }
    )
for issue in result["profiling_report"]["cross_column_issues"]:
    findings.append(
        {
            "Check": str(issue.get("type", "Cross-column check")),
            "Columns": ", ".join(map(str, issue.get("columns", []))),
            "Findings": str(issue.get("violation_count", "—")),
            "Details": str(issue.get("message", "Review related columns.")),
        }
    )

st.subheader("Quality findings")
if findings:
    st.dataframe(pd.DataFrame(findings), hide_index=True, use_container_width=True)
else:
    st.success("No missing-value, type, or supported cross-column issues detected.")
