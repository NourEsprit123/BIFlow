"""
BIFlow Analytics — KPI Calculation & Dynamic Chart Recommendation Module.
Provides deterministic calculation of business KPIs and automated chart recommendations
for any tabular dataset.
"""

from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd


def calculate_kpis(df: pd.DataFrame) -> List[Dict[str, str]]:
    """
    Computes exactly 4 high-value domain KPIs tailored to the given DataFrame.
    Returns a list of dicts with keys: 'title', 'value', 'subtitle'.
    """
    if df is None or df.empty:
        return [
            {"title": "Total Records", "value": "0", "subtitle": "Empty dataset"},
            {"title": "Features", "value": "0", "subtitle": "No columns"},
            {"title": "Data Quality", "value": "N/A", "subtitle": "No data"},
            {"title": "Completeness", "value": "0%", "subtitle": "0 cells"},
        ]

    n_rows, n_cols = df.shape
    num_df = df.select_dtypes(include=[np.number])
    cat_df = df.select_dtypes(include=["object", "category", "bool"])

    kpis = []

    # KPI 1: Volume / Population Size
    kpis.append({
        "title": "Total Records",
        "value": f"{n_rows:,}",
        "subtitle": f"{n_cols} attributes monitored"
    })

    # Domain specific heuristics:
    # Check for target/churn/status/default column
    target_col = None
    for col in df.columns:
        if col.lower() in ("churn", "target", "default", "status", "converted", "attrition", "is_churn"):
            target_col = col
            break

    if target_col is not None:
        val_counts = df[target_col].value_counts(normalize=True)
        # Find positive class
        pos_val = None
        for val in (1, "Yes", "yes", "True", "true", "churned", "Churn"):
            if val in val_counts.index:
                pos_val = val
                break
        if pos_val is None and len(val_counts) > 0:
            pos_val = val_counts.index[0]

        rate = (val_counts.get(pos_val, 0.0)) * 100
        count = df[target_col].value_counts().get(pos_val, 0)
        kpis.append({
            "title": f"{target_col.capitalize()} Rate",
            "value": f"{rate:.1f}%",
            "subtitle": f"{count:,} identified ({pos_val})"
        })
    elif len(num_df.columns) > 0:
        # Choose most representative numeric column
        primary_num = num_df.columns[0]
        mean_val = num_df[primary_num].mean()
        median_val = num_df[primary_num].median()
        kpis.append({
            "title": f"Avg {primary_num[:14]}",
            "value": f"{mean_val:,.2f}",
            "subtitle": f"Median: {median_val:,.2f}"
        })
    else:
        kpis.append({
            "title": "Total Columns",
            "value": str(n_cols),
            "subtitle": "Categorical attributes"
        })

    # KPI 3: Second numeric metric (Max, Peak, or Dispersion)
    if len(num_df.columns) > 1:
        sec_num = num_df.columns[1]
        max_val = num_df[sec_num].max()
        std_val = num_df[sec_num].std()
        kpis.append({
            "title": f"Max {sec_num[:14]}",
            "value": f"{max_val:,.2f}",
            "subtitle": f"Std Dev: ±{std_val:,.1f}"
        })
    elif len(num_df.columns) == 1:
        primary_num = num_df.columns[0]
        max_val = num_df[primary_num].max()
        min_val = num_df[primary_num].min()
        kpis.append({
            "title": f"Range ({primary_num[:12]})",
            "value": f"{min_val:,.0f} - {max_val:,.0f}",
            "subtitle": "Min to Max bounds"
        })
    else:
        # Categorical diversity
        kpis.append({
            "title": "Categorical Diversity",
            "value": f"{cat_df.iloc[:, 0].nunique():,}" if len(cat_df.columns) > 0 else "0",
            "subtitle": "Distinct classes"
        })

    # KPI 4: Completeness / Health Score
    total_cells = n_rows * n_cols
    missing_cells = df.isnull().sum().sum()
    completeness = ((total_cells - missing_cells) / max(total_cells, 1)) * 100
    kpis.append({
        "title": "Data Completeness",
        "value": f"{completeness:.1f}%",
        "subtitle": f"{missing_cells:,} missing values" if missing_cells > 0 else "Zero missing values"
    })

    return kpis[:4]


def recommend_charts(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Automatically selects 4 to 6 relevant charts based on column data types and cardinality.
    """
    if df is None or df.empty:
        return []

    num_cols = list(df.select_dtypes(include=[np.number]).columns)
    cat_cols = list(df.select_dtypes(include=["object", "category", "bool"]).columns)

    # Exclude ID columns from primary visualizations
    filtered_num = [c for c in num_cols if "id" not in c.lower() and "key" not in c.lower()]
    filtered_cat = [c for c in cat_cols if "id" not in c.lower() and "key" not in c.lower() and df[c].nunique() < 30]

    charts: List[Dict[str, Any]] = []

    # 1. Pie chart for categorical distribution (low cardinality)
    for c in filtered_cat:
        nu = df[c].nunique()
        if 2 <= nu <= 8:
            charts.append({
                "title": f"Distribution by {c}",
                "type": "pie",
                "column_x": c,
                "column_y": None
            })
            break

    # 2. Bar chart: Category breakdown vs Numeric mean
    if filtered_cat and filtered_num:
        best_cat = next((c for c in filtered_cat if 2 <= df[c].nunique() <= 15), filtered_cat[0])
        best_num = filtered_num[0]
        charts.append({
            "title": f"Average {best_num} by {best_cat}",
            "type": "bar",
            "column_x": best_cat,
            "column_y": best_num
        })
    elif filtered_cat:
        best_cat = filtered_cat[0]
        charts.append({
            "title": f"Frequency of {best_cat}",
            "type": "bar",
            "column_x": best_cat,
            "column_y": None
        })

    # 3. Histogram for primary continuous numeric distribution
    if filtered_num:
        charts.append({
            "title": f"Distribution of {filtered_num[0]}",
            "type": "histogram",
            "column_x": filtered_num[0],
            "column_y": None
        })

    # 4. Box plot for outliers / spread
    if len(filtered_num) > 1 and filtered_cat:
        charts.append({
            "title": f"Spread of {filtered_num[1]} across {filtered_cat[0]}",
            "type": "box",
            "column_x": filtered_cat[0],
            "column_y": filtered_num[1]
        })
    elif filtered_num:
        charts.append({
            "title": f"Outliers & Quartiles: {filtered_num[0]}",
            "type": "box",
            "column_x": filtered_num[0],
            "column_y": None
        })

    # 5. Additional Bar or Histogram if available
    if len(filtered_num) > 1:
        charts.append({
            "title": f"Frequency Curve of {filtered_num[1]}",
            "type": "histogram",
            "column_x": filtered_num[1],
            "column_y": None
        })

    return charts[:6]


# ── BI Analyst Sandbox Executor ───────────────────────────────────────────────
import threading
import traceback
import textwrap

_BI_SAFE_BUILTINS = {
    "len": len, "range": range, "enumerate": enumerate, "zip": zip,
    "min": min, "max": max, "sum": sum, "round": round, "abs": abs,
    "int": int, "float": float, "str": str, "bool": bool, "list": list,
    "dict": dict, "set": set, "tuple": tuple, "type": type,
    "isinstance": isinstance, "print": print, "repr": repr,
    "any": any, "all": all, "sorted": sorted, "map": map, "filter": filter,
    "None": None, "True": True, "False": False,
}


def run_bi_sandboxed_calc(code: str, df: "pd.DataFrame", timeout_sec: int = 5) -> tuple:
    """
    Safely execute LLM-generated Python code for BI metric calculation.

    The code MUST define:  def compute_insight(df) -> dict

    Returns: (result_dict, error_string_or_None)
      - On success : ({"key": value, ...}, None)
      - On failure : (None, "ErrorType: description")
    """
    namespace = {
        "__builtins__": _BI_SAFE_BUILTINS,
        "pd": pd,
        "np": np,
    }

    # Phase 1 — compile & exec the code definition (syntax / import errors caught here)
    try:
        exec(textwrap.dedent(code), namespace)  # noqa: S102
    except SyntaxError as exc:
        return None, f"SyntaxError: {exc}"
    except Exception as exc:
        return None, f"ExecError: {exc}"

    if "compute_insight" not in namespace:
        return None, "Code must define: def compute_insight(df) -> dict"

    # Phase 2 — call compute_insight(df) with a thread timeout
    result_box: list = [None]
    error_box:  list = [None]

    def _target():
        try:
            result_box[0] = namespace["compute_insight"](df.copy())
        except Exception:
            error_box[0] = traceback.format_exc()

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout=timeout_sec)

    if t.is_alive():
        return None, f"TimeoutError: execution exceeded {timeout_sec}s"

    return result_box[0], error_box[0]
