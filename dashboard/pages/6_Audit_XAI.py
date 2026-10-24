import streamlit as st

from components import setup, page_header, locked_feature
from workspace import (
    PROFILE_STATE_KEY,
    get_workspace_result,
    load_selected_dataset,
    profile_dataset_for_workspace,
    profiling_execution_status,
    profiling_report_json,
    verify_profiling_report,
)

setup("Audit & XAI")
locked_feature("Explainability / XAI")
page_header(
    "Audit & Explainability",
    "Inspect the profiling evidence and verify the report against the active dataset.",
    crumbs="Workspace › **Audit & XAI**",
)

path, frame = load_selected_dataset()
if path is None or frame is None:
    st.warning("Upload a dataset before generating an audit.")
    st.stop()

profile_result = get_workspace_result(PROFILE_STATE_KEY, path)
has_current_report = profile_result is not None

run_col, verify_col, export_col = st.columns(3)
with run_col:
    if st.button("Generate audit", type="primary", use_container_width=True):
        profile_dataset_for_workspace(path, refresh=True)
        st.rerun()
with verify_col:
    verify_clicked = st.button(
        "Verify current report",
        use_container_width=True,
        disabled=not has_current_report,
    )
with export_col:
    report_bytes = profiling_report_json() if has_current_report else None
    if report_bytes:
        st.download_button(
            "Export audit JSON",
            data=report_bytes,
            file_name=f"{path.stem}_audit.json",
            mime="application/json",
            use_container_width=True,
        )

if verify_clicked and profile_result:
    verification = verify_profiling_report(path, profile_result)
    if verification["verified"]:
        st.success(f"Verified saved report for {path.name}. SHA-256: {verification['sha256']}")
    else:
        st.error(f"Report verification failed: {verification['reason']}")

if has_current_report and profile_result:
    result = profile_result
    report = result["profiling_report"]
    used_llm, llm_message = profiling_execution_status(result)
    verification = verify_profiling_report(path, profile_result)
    st.subheader(f"Audit report · {path.name}")
    st.write(
        f"{result['profile']['rows']:,} rows × {result['profile']['columns']} columns · "
        f"Quality score {result['health']['overall_health_score']}% · "
        f"Report {'verified' if verification['verified'] else 'not verified'}"
    )
    (st.info if used_llm else st.warning)(llm_message)
    st.write(report.get("agent_summary", "No narrative summary was produced."))
    with st.expander("Profiling evidence"):
        st.json(report)
else:
    st.info("No current audit report. Generate one to view evidence and enable verification/export.")
