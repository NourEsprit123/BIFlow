import json

import streamlit as st

from components import setup, page_header, locked_feature
from workspace import analyze_dataframe, load_selected_dataset

setup("BI Analysis")
locked_feature("BI Analysis")
page_header(
    "Business Intelligence Analysis",
    "Explore metrics and distributions calculated from the active dataset.",
    crumbs="Workspace › **BI Analysis**",
)

path, frame = load_selected_dataset()
if path is None or frame is None:
    st.warning("Upload a dataset before running analysis.")
    st.stop()

analysis = analyze_dataframe(frame, path)
st.caption(f"Active dataset: {path.name} · {analysis['rows']:,} rows × {analysis['columns']} columns")

download_col, workflow_col = st.columns([1, 1])
with download_col:
    st.download_button(
        "Export analysis report",
        data=json.dumps(analysis, indent=2, default=str),
        file_name=f"{path.stem}_analysis.json",
        mime="application/json",
        use_container_width=True,
    )
with workflow_col:
    if st.button("Create workflow", type="primary", use_container_width=True):
        st.switch_page("pages/3_Workflows.py")

metrics = st.columns(4)
metrics[0].metric("Rows", f"{analysis['rows']:,}")
metrics[1].metric("Columns", analysis["columns"])
metrics[2].metric("Missing cells", f"{analysis['missing_cells']:,}")
metrics[3].metric(
    "Duplicate rows",
    f"{analysis['duplicate_rows']:,}",
)

if analysis["churn_rate"] is not None:
    metrics = st.columns(2)
    metrics[0].metric("Churn rate", f"{analysis['churn_rate']:.2f}%")
    metrics[1].metric(
        f"{analysis['churn_column']} positive records",
        f"{analysis['churn_count']:,}",
    )
else:
    st.info("No Churn / Is_Churn column found; churn metrics are not applicable to this dataset.")

numeric = frame.select_dtypes(include="number")
if not numeric.empty:
    st.subheader("Numeric column summary")
    st.dataframe(numeric.describe().T.round(3), use_container_width=True)

categorical = frame.select_dtypes(include=["object", "category", "bool"])
if not categorical.empty:
    st.subheader("Category distribution")
    column = st.selectbox("Categorical column", list(categorical.columns))
    counts = frame[column].astype("string").fillna("(missing)").value_counts().head(20)
    st.bar_chart(counts)

with st.expander("How these metrics are calculated"):
    st.write(
        "Counts and descriptive statistics are calculated directly from the selected file. "
        "When a Churn or Is_Churn column is present, values Yes, True, 1, Churn, and Churned "
        "are counted as positive records; null and empty values are excluded from the rate."
    )
