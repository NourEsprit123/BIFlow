from pathlib import Path

import streamlit as st

from components import setup, page_header
from workspace import dataset_label, list_datasets, load_dataset, save_uploaded_dataset, selected_dataset_path

setup("Datasets")
page_header("Your datasets", "Import data, find a file, and choose what the agents will work on.")

with st.expander("Import a dataset", expanded=False):
    uploaded = st.file_uploader("CSV, Excel or Parquet", type=["csv", "xlsx", "xls", "parquet"], key="dataset_upload")
    if st.button("Import and select dataset", type="primary", disabled=uploaded is None):
        try:
            destination = save_uploaded_dataset(uploaded)
            st.session_state["workspace_new_dataset_path"] = str(destination)
            st.session_state["dataset_import_notice"] = f"Imported and selected {destination.name}."
            st.rerun()
        except (ValueError, OSError) as exc:
            st.error(f"Import failed: {exc}")

notice = st.session_state.pop("dataset_import_notice", None)
if notice:
    st.success(notice)
query = st.text_input("Find a dataset", placeholder="Filter by filename or dataset name...", key="dataset_library_query").strip().casefold()
datasets = list_datasets()
matching = [p for p in datasets if query in p.name.casefold() or query in dataset_label(p).casefold()]
st.caption(f"{len(matching)} of {len(datasets)} datasets · Selecting a file updates every page and agent.")
active = selected_dataset_path()
if not matching:
    st.info("No matching datasets. Change the filter or import a new file.")
for path in matching:
    with st.container(border=True):
        detail, action = st.columns([4, 1], vertical_alignment="center")
        with detail:
            st.markdown(f"**{dataset_label(path)}**")
            try:
                frame = load_dataset(str(path))
                st.caption(f"{path.name} · {len(frame):,} rows · {len(frame.columns)} columns · {path.stat().st_size / 1024:,.1f} KB")
            except Exception as exc:
                st.error(f"This file could not be read: {exc}")
                continue
        with action:
            if st.button("Selected" if path == active else "Use dataset", key=f"select_{path.name}", disabled=path == active, use_container_width=True):
                st.session_state["workspace_new_dataset_path"] = str(path)
                st.rerun()
        with st.expander(f"Preview {path.name}"):
            st.dataframe(frame.head(10), hide_index=True, use_container_width=True)
