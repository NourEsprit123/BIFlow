from pathlib import Path

import pandas as pd
import streamlit as st

from components import setup, page_header
from workspace import RAW_DATA, dataset_label, list_datasets, load_dataset, save_uploaded_dataset

setup("Datasets")
page_header(
    "Datasets",
    "Upload, select, and inspect the data files used by your BIFlow agents.",
    crumbs="Workspace › <b>Datasets</b>",
)

with st.expander("Upload a dataset", expanded=False):
    uploaded = st.file_uploader(
        "Choose a CSV, Excel, or Parquet file",
        type=["csv", "xlsx", "xls", "parquet"],
        key="dataset_upload",
    )
    if st.button("Import dataset", type="primary", disabled=uploaded is None):
        if uploaded is not None:
            destination = save_uploaded_dataset(uploaded)
            st.session_state["workspace_new_dataset_path"] = str(destination)
            st.success(f"Imported {destination.name}.")
            st.rerun()

left, right = st.columns([3, 1])
with left:
    query = st.session_state.get("workspace_search_query", "").casefold()
    st.caption(
        f"Search filter: {query}" if query else "Use the Search datasets field in the top bar to filter."
    )
with right:
    st.write("")
    st.write("")
    if st.button("Refresh list", use_container_width=True):
        st.rerun()

datasets = list_datasets()
rows = []
for path in datasets:
    if query and query not in path.name.casefold():
        continue
    frame = load_dataset(str(path))
    rows.append({
        "Dataset": dataset_label(path),
        "File": path.name,
        "Format": path.suffix.lstrip(".").upper(),
        "Rows": len(frame),
        "Columns": len(frame.columns),
        "Missing cells": int(frame.isna().sum().sum()),
        "Size": f"{path.stat().st_size / 1024:,.1f} KB",
        "Selected": str(path) == st.session_state.get("workspace_dataset_path"),
    })

if rows:
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    active = st.session_state.get("workspace_dataset_path")
    if active:
        st.caption(f"Active dataset: {Path(active).name}")
else:
    st.info("No matching datasets. Upload a CSV, Excel, or Parquet file to begin.")

total_bytes = sum(path.stat().st_size for path in datasets)
st.subheader("Local workspace")
storage, sources = st.columns(2)
with storage:
    st.metric("Dataset files", len(datasets))
    st.caption(f"{total_bytes / (1024 * 1024):,.2f} MB stored under `{RAW_DATA}`.")
with sources:
    st.metric("Available formats", ", ".join(sorted({p.suffix.lstrip(".").upper() for p in datasets})) or "None")
    st.caption("Connected database and cloud connectors are not configured in this build.")
