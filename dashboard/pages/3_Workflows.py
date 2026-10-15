import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import streamlit as st

from agents.data_engineering_agent import DataEngineeringAgent
from agents.bi_analyst_agent import BIAnalystAgent
from components import setup, page_header, btn, html, badge

setup("Workflows")
page_header(
    "Create Analysis Workflow",
    "Configure autonomous multi-agent pipeline tasks and intelligence parameters for your dataset.",
    badge("● Draft workflow", "gray"),
)

RAW_DIR = os.path.join("data", "raw")
SUPPORTED_FORMATS = (".csv", ".xlsx", ".xls", ".parquet")
os.makedirs(RAW_DIR, exist_ok=True)

html('''<div class="bf-card" style="display:flex;gap:2rem;align-items:center;margin-bottom:1rem">
  <b style="color:#4338ca">✔ Dataset</b> › <b>② Tasks</b> › <span style="color:#64748b">③ Preferences</span>
  <span class="mono" style="margin-left:auto;font-size:.8rem">⏱ Estimated runtime: <b>2-4 min</b></span></div>''')

def section(n, title, sub, body):
    return f'''<div style="display:grid;grid-template-columns:1fr 3fr;gap:1.5rem;margin-bottom:1.5rem">
      <div><b style="background:#4338ca;color:#fff;border-radius:50%;padding:.1rem .5rem">{n}</b> <b>{title}</b><br><small style="color:#64748b">{sub}</small></div>
      <div>{body}</div></div>'''

datasets = sorted(
    file_name
    for file_name in os.listdir(RAW_DIR)
    if file_name.lower().endswith(SUPPORTED_FORMATS)
)

pending_dataset = st.session_state.pop("workflow_pending_dataset", None)
if pending_dataset in datasets:
    st.session_state["workflow_selected_dataset"] = pending_dataset

if datasets:
    default_dataset = st.session_state.get("workflow_selected_dataset")
    dataset_index = datasets.index(default_dataset) if default_dataset in datasets else 0
    selected_file = st.selectbox(
        "Select dataset for this workflow",
        options=datasets,
        index=dataset_index,
        key="workflow_selected_dataset",
    )
    file_path = os.path.join(RAW_DIR, selected_file)
    dataset_card = f'''<div class="bf-card" style="background:#eef2ff;display:flex;gap:1rem;align-items:center">🗄
      <div><b>{selected_file}</b> <span class="bf-badge blue">{selected_file.rsplit(".", 1)[-1].upper()} Data Source</span><br>
      <small>Original file: <span class="mono">{file_path}</span></small></div>
      <span style="margin-left:auto"><span class="bf-badge">Selected</span></span></div>'''
else:
    dataset_card = (
        '<div class="bf-card" style="background:#eef2ff">'
        'Upload a supported file below to configure this workflow.</div>'
    )
html(section(1, "Select dataset", "Choose or upload your data source", dataset_card))

with st.form("workflow_dataset_upload", clear_on_submit=True):
    uploaded_file = st.file_uploader(
        "Upload a dataset",
        type=["csv", "xlsx", "xls", "parquet"],
        help="Supported files are added to data/raw/ and the original is preserved.",
    )
    upload_submitted = st.form_submit_button("Add dataset to workflow")

if upload_submitted:
    if uploaded_file is None:
        st.error("Choose a CSV, Excel, or Parquet file to upload.")
    else:
        safe_name = os.path.basename(uploaded_file.name)
        if not safe_name.lower().endswith(SUPPORTED_FORMATS):
            st.error("Unsupported dataset format.")
        else:
            save_path = os.path.join(RAW_DIR, safe_name)
            try:
                with open(save_path, "xb") as dataset_file:
                    dataset_file.write(uploaded_file.getbuffer())
            except FileExistsError:
                st.error(
                    f"`{safe_name}` already exists in `data/raw/`. "
                    "Choose it above or rename the file before uploading."
                )
            except OSError as error:
                st.error(f"Could not save the uploaded dataset: {error}")
            else:
                st.session_state["workflow_pending_dataset"] = safe_name
                st.success(f"Added **{safe_name}** to the workflow.")
                st.rerun()

if not datasets:
    st.stop()

html(section(
    2,
    "Analysis tasks",
    "Select one or more workflow cards to run or open.",
    "",
))
profiling_col, quality_col, bi_col = st.columns(3)
with profiling_col:
    with st.container(border=True):
        st.markdown("### Data Profiling")
        st.write(
            "Profile the dataset structure, column types, distributions, "
            "and cardinality with the configured LLM."
        )
        select_profiling = st.checkbox(
            "Select Data Profiling",
            key="workflow_select_profiling",
        )
        st.caption("The profile results open on the Datasets page.")
with quality_col:
    with st.container(border=True):
        st.markdown("### Data Quality + Cleaning + ETL")
        st.write(
            "Review detected quality issues, preview recommended corrections, "
            "then apply cleaning and load the validated dataset."
        )
        select_quality = st.checkbox(
            "Select Data Quality + Cleaning + ETL",
            key="workflow_select_data_quality",
        )
        st.caption("The selected dataset opens on Data Quality; cleaning remains under your control.")
with bi_col:
    with st.container(border=True):
        st.markdown("### Profiling + Cleaning + KPI Dashboard")
        st.write(
            "Run profiling and validated cleaning first, then calculate KPIs, "
            "build dashboards, and generate LLM insights from the cleaned dataset."
        )
        select_bi_analysis = st.checkbox(
            "Select full BI pipeline",
            key="workflow_select_bi_analysis",
        )
        st.caption("The full sequence runs automatically and opens the cleaned dataset analysis.")

if select_profiling and select_quality and select_bi_analysis:
    selected_workflows_label = "Profiling + Cleaning + ETL + KPI Dashboard + AI Insights"
elif select_profiling and select_quality:
    selected_workflows_label = "Data Profiling + Data Quality + Cleaning + ETL"
elif select_profiling and select_bi_analysis:
    selected_workflows_label = "Profiling + Cleaning + ETL + BI Analysis"
elif select_quality and select_bi_analysis:
    selected_workflows_label = "Profiling + Cleaning + ETL + BI Analysis"
elif select_profiling:
    selected_workflows_label = "Data Profiling"
elif select_quality:
    selected_workflows_label = "Data Quality + Cleaning + ETL"
elif select_bi_analysis:
    selected_workflows_label = "Profiling + Cleaning + ETL + KPI Dashboard + AI Insights"
else:
    selected_workflows_label = "No workflow selected"

tasks = [
    ("KPI Analysis", "Calculate enterprise churn velocity, revenue risk, and LTV", "BI Engine", "~40 sec"),
    ("Trend Analysis", "Reveal movement and temporal churn shifts across rolling cohorts", "Temporal", "Optional"),
    ("Anomaly Detection", "Surface statistical outliers and abrupt churn pattern spikes", "ML Detector", "Optional"),
    ("Segmentation", "Discover meaningful customer clusters based on service behavior", "Clustering", "Optional"),
    ("AI Insights", "Generate actionable natural language business findings and trends", "LLM Analyst", "~50 sec"),
    ("XAI / Audit", "Explain and trace every mathematical calculation and heuristic", "Transparency", "~30 sec"),
]
cards = "".join(
    f'''<div class="bf-task"><span class="chk"></span>
      <span>⚙</span><h4>{title}</h4><p>{description}</p>
      <span class="bf-badge gray mono">{agent_name}</span> <small>{runtime}</small></div>'''
    for title, description, agent_name, runtime in tasks
)
html(f'<div class="bf-grid g2">{cards}</div>')

pref = lambda title, description, value: (
    f'<div class="bf-card" style="margin-bottom:.7rem;display:flex;justify-content:space-between">'
    f'<div><b>{title}</b><br><small>{description}</small></div>{value}</div>'
)
prefs = (
    pref("Execution priority", "Standard balances speed and autonomous compute cluster usage.", btn("Standard") + btn("Fast"))
    + pref("AI explanation", "Explain step-by-step how each business insight and metric was generated.", badge("ENABLED ●"))
    + pref("Generate recommendations", "Add prescriptive strategic playbooks and actions to key findings.", badge("ENABLED ●"))
)
html(section(3, "Preferences", "Configure this run", prefs))

agent = DataEngineeringAgent()
bi_agent = BIAnalystAgent()
selected_count = int(select_profiling) + int(select_quality) + int(select_bi_analysis)
html(f'''<div class="bf-card" style="display:flex;gap:1rem;align-items:center">
  {badge(f"{selected_count} workflows selected")} {selected_file} · {selected_workflows_label}</div>''')
run_selected_workflows = st.button(
    "▷ Execute selected workflows",
    type="primary",
    use_container_width=True,
    key="execute_selected_workflows",
    disabled=selected_count == 0,
)

if run_selected_workflows:
    st.session_state["active_dataset"] = file_path
    st.session_state["workflow_dataset_scope"] = selected_file
    st.session_state["dq_dataset_select"] = selected_file

    if select_quality and not select_profiling:
        if not select_bi_analysis:
            st.session_state.pop("workflow_profile_result", None)
            st.session_state.pop("workflow_profile_dataset", None)
            st.switch_page("pages/4_Data_Quality.py")

    if select_bi_analysis:
        try:
            with st.spinner(
                f"Running profiling, quality cleaning, and ETL for {selected_file}..."
            ):
                pipeline = bi_agent.run_pipeline(file_path)
        except (RuntimeError, ValueError, OSError) as error:
            st.error(f"Profile and cleaning pipeline failed. Details: {error}")
            st.stop()
        st.session_state["workflow_profile_result"] = {
            "status": pipeline["status"],
            "workflow": "profiling",
            "profile": pipeline["profile"],
        }
        st.session_state["workflow_profile_dataset"] = selected_file
        cleaned_path = pipeline["cleaned_dataset_path"]
        st.session_state["workflow_cleaned_dataset_path"] = cleaned_path
        st.session_state["workflow_cleaned_dataset_source"] = selected_file

        dataset_stat = os.stat(cleaned_path)
        st.session_state["bi_analysis_result"] = pipeline["analysis"]
        st.session_state["bi_analysis_dataset"] = selected_file
        st.session_state["bi_analysis_source_path"] = cleaned_path
        st.session_state["bi_analysis_fingerprint"] = (
            dataset_stat.st_size,
            dataset_stat.st_mtime_ns,
        )
        st.switch_page("pages/5_BI_Analysis.py")

    if select_profiling:
        try:
            with st.spinner(f"LLM is running Data Profiling for {selected_file}..."):
                result = agent.run_workflow(file_path, "profiling")
        except (RuntimeError, ValueError, OSError) as error:
            st.error(f"Data profiling failed. Details: {error}")
            st.stop()
        st.session_state["workflow_profile_result"] = result
        st.session_state["workflow_profile_dataset"] = selected_file

    if select_profiling:
        st.switch_page("pages/2_Datasets.py")
