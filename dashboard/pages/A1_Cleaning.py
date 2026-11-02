import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.cleaning_review import render_cleaning_result, run_cleaning_with_progress, render_experiment_runtime, render_cleaning_limits
from components import setup, page_header, badge, dataset_picker
from agents.dataCleaning_agent import publish_cleaned
from workspace import CLEANED_DATA, CLEANING_STATE_KEY, get_workspace_result

setup("Data Cleaning", hub="Agent 2 · Data Cleaning")
page_header(
    "Data Cleaning",
    "Tested, versioned cleaning of the active dataset: what changed, what needs your decision and the full trace.",
    badge("Agent 2", "green"),
    "Agent 2 · Data Cleaning > <b>Cleaning run</b>",
)

if st.session_state.pop("cleaning_just_finished", False):
    st.toast("Cleaning finished. Here is what changed and what needs you.", icon="✅")


def remember_experiment_preference():
    st.session_state["prefer_generated_methods"] = st.session_state["experiment_mode_widget"]


path = dataset_picker()
if path is None:
    st.stop()

run_col, note_col = st.columns([1, 2], vertical_alignment="center")
with run_col:
    run_clicked = st.button("🧹 Run Data Cleaning Agent", type="primary", width="stretch", key="cleaner_run")
with note_col:
    st.caption("Uses the profiling report of the active dataset (it is created first if missing). "
               "The uploaded file is never modified; every change is a new version.")
if run_clicked:
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
if cleaning and not (CLEANED_DATA / f"{cleaning.final_dataset.dataset_id}_cleaned.csv").exists():
    publish_cleaned(cleaning, CLEANED_DATA)  # a run from before results were published for the BI Analyst
run_tab, settings_tab = st.tabs(["Cleaning run", "Run settings"])

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
        st.info("Run the Data Cleaning Agent to see what was fixed, what needs your approval and the full trace here. "
                "Runs started from Workflows appear here too.")
        st.page_link("pages/A1_Quality.py", label="Review source-file quality first", icon="✅")
