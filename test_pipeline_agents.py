"""
BIFlow - Multi-Agent Sequential POC Pipeline
=============================================
Fully self-contained, dataset-agnostic script. Accepts ANY CSV file —
no hardcoded column names. Connects to a local Ollama instance (qwen2.5:7b)
for LLM reasoning layers, with deterministic Pandas/NumPy computations
as the data foundation.

Run: streamlit run test_pipeline_agents.py
"""

import json
import os

import numpy as np
import pandas as pd
import requests
import streamlit as st

# ---------------------------------------------------------------------------
# 0. INFRASTRUCTURE CONFIGURATION
# ---------------------------------------------------------------------------

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5:7b"
DEFAULT_DATA_PATH = os.path.join(
    os.path.dirname(__file__), "data", "raw", "telco_churn.csv"
)


# ---------------------------------------------------------------------------
# 1. OLLAMA CLIENT  (robust fallback on timeout / connection error)
# ---------------------------------------------------------------------------

def query_ollama(system_prompt: str, user_message: str, timeout: int = 120) -> str:
    """
    POST a generate request to the local Ollama instance.
    Returns the model's text response, or a clean fallback string on failure.
    Uses stream=True to consume the NDJSON response line-by-line.
    """
    payload = {
        "model": MODEL,
        "system": system_prompt,
        "prompt": user_message,
        "stream": True,
    }
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=timeout, stream=True)
        response.raise_for_status()

        collected = []
        for raw_line in response.iter_lines():
            if raw_line:
                try:
                    chunk = json.loads(raw_line.decode("utf-8"))
                    collected.append(chunk.get("response", ""))
                    if chunk.get("done", False):
                        break
                except json.JSONDecodeError:
                    continue

        full_text = "".join(collected).strip()
        return full_text if full_text else "[Ollama returned an empty response.]"

    except requests.exceptions.ConnectionError:
        return (
            "⚠️  **Ollama Connection Error** — Make sure Ollama is running on "
            f"`{OLLAMA_URL}`. Start it with: `ollama serve`"
        )
    except requests.exceptions.Timeout:
        return (
            "⚠️  **Ollama Timeout** — The model took too long to respond. "
            "Try a shorter prompt or increase the timeout value."
        )
    except requests.exceptions.RequestException as exc:
        return f"⚠️  **Ollama Request Error** — {exc}"


# ---------------------------------------------------------------------------
# 2. SCHEMA INTROSPECTION — derive column roles from any dataframe
# ---------------------------------------------------------------------------

def introspect_schema(df: pd.DataFrame) -> dict:
    """
    Dynamically resolve which columns fill each semantic role.
    Returns a dict with keys:
        all_columns       — list of all column names
        numeric_cols      — list of numeric column names (after coercion)
        categorical_cols  — list of object/category column names
        primary_numeric   — first numeric column (primary financial indicator)
        primary_category  — first categorical column (primary segment indicator)
    All columns are coerced to numeric where possible so dirty string-numeric
    columns (e.g. TotalCharges with whitespace) are handled transparently.
    """
    df_coerced = df.copy()

    # Attempt numeric coercion on every object column — captures dirty columns
    # like TotalCharges that should be numeric but contain whitespace/strings.
    for col in df_coerced.select_dtypes(include=["object"]).columns:
        coerced = pd.to_numeric(df_coerced[col], errors="coerce")
        # Only upgrade dtype if > 50% of non-null values parsed successfully
        if coerced.notna().sum() > df_coerced[col].notna().sum() * 0.5:
            df_coerced[col] = coerced

    numeric_cols = df_coerced.select_dtypes(include=["number"]).columns.tolist()
    categorical_cols = df_coerced.select_dtypes(
        include=["object", "category"]
    ).columns.tolist()

    return {
        "all_columns": df.columns.tolist(),
        "numeric_cols": numeric_cols,
        "categorical_cols": categorical_cols,
        "primary_numeric": numeric_cols[0] if numeric_cols else None,
        "primary_category": categorical_cols[0] if categorical_cols else None,
        "df_coerced": df_coerced,
    }


# ---------------------------------------------------------------------------
# 3. AGENT 1 — DATA ENGINEERING AGENT (fully schema-agnostic)
# ---------------------------------------------------------------------------

def run_data_engineering_agent(df: pd.DataFrame) -> tuple[dict, str]:
    """
    Step 1 — Deterministic data quality matrix across ALL columns (pure Pandas).
    Step 2 — LLM reasoning layer: Ollama generates a Data Health Evaluation Report.

    Returns:
        quality_matrix (dict): raw numerical results for UI display
        report (str):          LLM-generated narrative health assessment
    """
    schema = introspect_schema(df)
    total_rows = len(df)

    # --- Deterministic computation across every column ----------------------
    quality_matrix = {}
    for col in df.columns:
        missing_count = int(df[col].isna().sum())
        missing_pct = round((missing_count / total_rows) * 100, 2)
        quality_matrix[col] = {
            "dtype": str(df[col].dtype),
            "missing_count": missing_count,
            "missing_pct": missing_pct,
        }

    duplicate_count = int(df.duplicated().sum())
    quality_matrix["__duplicates__"] = duplicate_count
    quality_matrix["__schema__"] = schema

    # --- Format context for LLM ---------------------------------------------
    lines = [
        f"Dataset shape   : {total_rows} rows × {df.shape[1]} columns",
        f"Duplicate rows  : {duplicate_count}",
        f"Numeric columns : {schema['numeric_cols']}",
        f"Text columns    : {schema['categorical_cols']}",
        "",
        "Per-column quality metrics:",
    ]
    for col in df.columns:
        m = quality_matrix[col]
        lines.append(
            f"  • {col:25s}  dtype={m['dtype']:12s}  "
            f"missing={m['missing_count']:4d} ({m['missing_pct']}%)"
        )

    context_block = "\n".join(lines)

    system_prompt = (
        "You are a senior Data Engineering Agent in a Business Intelligence pipeline. "
        "Your task is to evaluate the data quality metrics provided and produce a "
        "concise, structured Data Health Evaluation Report. "
        "Cover: overall data health score (High / Medium / Low), key risk areas, "
        "recommended preprocessing steps, and a one-line readiness verdict. "
        "Write in professional prose with clear section headings. Be concise."
    )
    user_message = (
        "Here are the data quality metrics for the uploaded dataset:\n\n"
        + context_block
        + "\n\nGenerate the Data Health Evaluation Report."
    )

    report = query_ollama(system_prompt, user_message)
    return quality_matrix, report


# ---------------------------------------------------------------------------
# 4. AGENT 2 — BI ANALYST AGENT (fully schema-agnostic)
# ---------------------------------------------------------------------------

def run_bi_analyst_agent(df: pd.DataFrame, data_health_report: str) -> tuple[dict, str]:
    """
    Step 1 — Dynamic KPI computation using schema introspection (no hardcoded columns).
    Step 2 — LLM reasoning layer: Ollama generates Strategic Business Recommendations.

    Primary numeric column  → treated as the main financial / operational indicator.
    Primary categorical col → treated as the segmentation / status dimension.

    Returns:
        kpis (dict): raw KPI values for UI display
        recommendations (str): LLM-generated strategic narrative
    """
    schema = introspect_schema(df)
    df_coerced = schema["df_coerced"]
    total_rows = len(df_coerced)

    # --- Resolve column roles -----------------------------------------------
    primary_num = schema["primary_numeric"]
    primary_cat = schema["primary_category"]

    if primary_num is None:
        return (
            {"error": "No numeric columns detected in this dataset."},
            "⚠️  No numeric columns found. Agent 2 requires at least one numeric column.",
        )

    # --- Deterministic KPI computation --------------------------------------
    num_series = pd.to_numeric(df_coerced[primary_num], errors="coerce")

    total_numeric_sum = round(float(num_series.sum(skipna=True)), 2)
    avg_numeric = round(float(num_series.mean(skipna=True)), 2)
    median_numeric = round(float(num_series.median(skipna=True)), 2)
    null_count_numeric = int(num_series.isna().sum())
    valid_count_numeric = int(num_series.notna().sum())

    # Categorical segmentation
    cat_segment_counts: dict = {}
    unique_cat_count: int = 0
    top_segment: str = "N/A"
    top_segment_count: int = 0

    if primary_cat is not None:
        cat_series = df_coerced[primary_cat].astype(str).str.strip().str.title()
        unique_cat_count = int(cat_series.nunique())
        segment_counts = cat_series.value_counts()
        cat_segment_counts = segment_counts.head(5).to_dict()
        top_segment = str(segment_counts.index[0])
        top_segment_count = int(segment_counts.iloc[0])

    kpis = {
        "total_rows": total_rows,
        "primary_numeric_col": primary_num,
        "primary_category_col": primary_cat if primary_cat else "N/A",
        "numeric_sum": total_numeric_sum,
        "numeric_avg": avg_numeric,
        "numeric_median": median_numeric,
        "numeric_null_count": null_count_numeric,
        "numeric_valid_count": valid_count_numeric,
        "unique_cat_count": unique_cat_count,
        "top_segment": top_segment,
        "top_segment_count": top_segment_count,
        "cat_segment_counts": cat_segment_counts,
    }

    # --- Format context for LLM ---------------------------------------------
    seg_lines = "\n".join(
        f"    {seg}: {cnt} records"
        for seg, cnt in cat_segment_counts.items()
    )

    kpi_block = (
        f"Total Records              : {total_rows:,}\n"
        f"\n"
        f"Primary Numeric Indicator  : '{primary_num}'\n"
        f"  Sum                      : {total_numeric_sum:,.2f}\n"
        f"  Average                  : {avg_numeric:,.2f}\n"
        f"  Median                   : {median_numeric:,.2f}\n"
        f"  Valid (non-null) values  : {valid_count_numeric:,} / {total_rows:,}\n"
        f"  Missing values           : {null_count_numeric:,}\n"
        f"\n"
        f"Primary Segment Dimension  : '{primary_cat}'\n"
        f"  Unique segment values    : {unique_cat_count}\n"
        f"  Top segment              : '{top_segment}' ({top_segment_count:,} records)\n"
        f"  Top-5 segment breakdown  :\n{seg_lines}\n"
    )

    system_prompt = (
        "You are a senior BI Analyst Agent in a Business Intelligence pipeline. "
        "You receive validated KPI data computed directly from a business dataset. "
        "The primary numeric column is the main financial or operational indicator "
        "(e.g. revenue, transaction amount, charges). "
        "The primary categorical column represents the segmentation or status dimension. "
        "Your task: interpret these metrics, identify business risks and opportunities, "
        "and produce 3–5 prioritised, actionable strategic recommendations. "
        "Write in professional, executive-ready prose. Be specific and data-driven."
    )
    user_message = (
        "The Data Engineering Agent validated this dataset with the following assessment "
        "(summary):\n\n"
        f"{data_health_report[:600]}...\n\n"
        "---\n"
        "Computed business KPIs from the validated dataset:\n\n"
        + kpi_block
        + "\n\nGenerate the Strategic Business Recommendations report."
    )

    recommendations = query_ollama(system_prompt, user_message)
    return kpis, recommendations


# ---------------------------------------------------------------------------
# 5. STREAMLIT UI
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(
        page_title="BIFlow — Multi-Agent Sequential POC Pipeline",
        layout="wide",
        page_icon="🔁",
    )

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------
    st.title("🔁 BIFlow — Multi-Agent Sequential POC Pipeline")
    st.caption(
        f"Powered by **Ollama** · Model: `{MODEL}` · "
        "Agent 1 → Agent 2 sequential execution · Dataset-agnostic"
    )
    st.divider()

    # ------------------------------------------------------------------
    # Data source
    # ------------------------------------------------------------------
    st.subheader("📂 Data Source")
    uploaded_file = st.file_uploader(
        "Upload any CSV file — or leave blank to auto-load the default Telco Churn dataset",
        type=["csv"],
    )

    if uploaded_file is not None:
        df = pd.read_csv(uploaded_file)
        data_source_label = f"Uploaded: `{uploaded_file.name}`"
    else:
        if not os.path.exists(DEFAULT_DATA_PATH):
            st.error(
                f"Default dataset not found at `{DEFAULT_DATA_PATH}`. "
                "Please upload a CSV file above."
            )
            st.stop()
        df = pd.read_csv(DEFAULT_DATA_PATH)
        data_source_label = "Auto-loaded: `data/raw/telco_churn.csv`"

    st.success(
        f"{data_source_label} — **{len(df):,} rows × {df.shape[1]} columns** loaded."
    )

    # Schema preview
    schema = introspect_schema(df)
    with st.expander("🔍 Detected Schema", expanded=False):
        col_a, col_b = st.columns(2)
        with col_a:
            st.write("**Numeric columns**")
            st.write(schema["numeric_cols"] or "None detected")
        with col_b:
            st.write("**Categorical columns**")
            st.write(schema["categorical_cols"] or "None detected")
        st.write(
            f"**Primary numeric indicator:** `{schema['primary_numeric']}`  |  "
            f"**Primary segment column:** `{schema['primary_category']}`"
        )

    st.divider()

    # ------------------------------------------------------------------
    # Run button
    # ------------------------------------------------------------------
    run_col, _ = st.columns([1, 4])
    with run_col:
        run_pipeline = st.button(
            "▶  Run Sequential Agent Pipeline",
            use_container_width=True,
            type="primary",
        )

    if not run_pipeline:
        st.info("Click **Run Sequential Agent Pipeline** to start the POC.")
        st.stop()

    # ------------------------------------------------------------------
    # AGENT 1 — DATA ENGINEERING
    # ------------------------------------------------------------------
    st.divider()
    st.subheader("🛠️  Agent 1 — Data Engineering Agent")

    with st.spinner("Agent 1: Computing data quality matrix across all columns..."):
        quality_matrix, data_health_report = run_data_engineering_agent(df)

    # Deterministic metrics — show up to 6 columns, skip internal keys
    display_cols = [c for c in df.columns if not c.startswith("__")][:6]
    qm_grid = st.columns(len(display_cols))
    for idx, col_name in enumerate(display_cols):
        m = quality_matrix.get(col_name, {})
        with qm_grid[idx]:
            pct = m.get("missing_pct", 0.0)
            delta_color = "normal" if pct == 0 else "inverse"
            st.metric(
                label=col_name,
                value=f"{pct}% missing",
                delta=m.get("dtype", "—"),
                delta_color=delta_color,
            )

    dup_count = quality_matrix.get("__duplicates__", 0)
    st.metric(label="Duplicate Rows", value=f"{dup_count:,}")

    st.subheader("📋 Data Health Evaluation Report")
    st.info(data_health_report)

    # ------------------------------------------------------------------
    # AGENT 2 — BI ANALYST
    # ------------------------------------------------------------------
    st.divider()
    st.subheader("📊  Agent 2 — BI Analyst Agent")

    with st.spinner("Agent 2: Computing dynamic KPIs and generating recommendations..."):
        kpis, recommendations = run_bi_analyst_agent(df, data_health_report)

    if "error" in kpis:
        st.error(kpis["error"])
    else:
        primary_num = kpis["primary_numeric_col"]
        primary_cat = kpis["primary_category_col"]

        # KPI metrics — 4 dynamic cards
        kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)

        with kpi_col1:
            st.metric(
                label="Total Records",
                value=f"{kpis['total_rows']:,}",
                delta=f"{kpis['numeric_valid_count']:,} valid numeric rows",
            )
        with kpi_col2:
            st.metric(
                label=f"Sum · {primary_num}",
                value=f"{kpis['numeric_sum']:,.2f}",
                delta=f"Avg: {kpis['numeric_avg']:,.2f}",
            )
        with kpi_col3:
            st.metric(
                label=f"Median · {primary_num}",
                value=f"{kpis['numeric_median']:,.2f}",
                delta=f"Missing: {kpis['numeric_null_count']:,} rows",
                delta_color="inverse" if kpis["numeric_null_count"] > 0 else "normal",
            )
        with kpi_col4:
            st.metric(
                label=f"Segments · {primary_cat}",
                value=f"{kpis['unique_cat_count']} unique",
                delta=f"Top: '{kpis['top_segment']}' ({kpis['top_segment_count']:,})",
            )

        # Segment breakdown table
        if kpis["cat_segment_counts"]:
            with st.expander(f"📂 Top-5 Segment Breakdown — `{primary_cat}`", expanded=True):
                seg_df = pd.DataFrame(
                    list(kpis["cat_segment_counts"].items()),
                    columns=[primary_cat, "Count"],
                )
                seg_df["Share %"] = (
                    seg_df["Count"] / kpis["total_rows"] * 100
                ).round(2)
                st.dataframe(seg_df, use_container_width=True, hide_index=True)

    st.subheader("💡 Strategic Business Recommendations")
    st.info(recommendations)

    # ------------------------------------------------------------------
    # Pipeline summary footer
    # ------------------------------------------------------------------
    st.divider()
    if "error" not in kpis:
        st.success(
            f"✅ **Sequential pipeline complete.** "
            f"Agent 1 → Agent 2 executed successfully. "
            f"Primary indicator `{kpis['primary_numeric_col']}` · "
            f"Sum: **{kpis['numeric_sum']:,.2f}** · "
            f"Avg: **{kpis['numeric_avg']:,.2f}** · "
            f"Segments detected: **{kpis['unique_cat_count']}**"
        )
    else:
        st.warning("Pipeline completed with warnings. Review Agent 2 output above.")


# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    main()
