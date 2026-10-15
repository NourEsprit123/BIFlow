from typing import Any, Dict, List

import numpy as np
import pandas as pd

from analytics.profiler import infer_column_roles


MAX_NUMERIC_COLUMNS = 12
MAX_CATEGORICAL_COLUMNS = 6
MAX_CATEGORIES_PER_COLUMN = 10


def calculate_kpis(df: pd.DataFrame) -> Dict[str, Any]:
    """Calculate dataset-level KPIs and chart-ready aggregates without exposing rows."""
    row_count, column_count = df.shape
    total_cells = row_count * column_count
    missing_cells = int(df.isna().sum().sum())
    duplicate_rows = int(df.duplicated().sum())
    roles = infer_column_roles(df)

    numeric_metrics: Dict[str, Dict[str, Any]] = {}
    numeric_columns = [
        column for column, role in roles.items()
        if role == "continuous_numeric"
        and pd.api.types.is_numeric_dtype(df[column])
    ][:MAX_NUMERIC_COLUMNS]
    for column in numeric_columns:
        values = pd.to_numeric(df[column], errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        ).dropna()
        if values.empty:
            continue
        numeric_metrics[str(column)] = {
            "count": int(values.size),
            "mean": float(values.mean()),
            "median": float(values.median()),
            "min": float(values.min()),
            "max": float(values.max()),
            "sum": float(values.sum()),
            "std": float(values.std()) if values.size > 1 else 0.0,
        }

    categorical_distributions: Dict[str, List[Dict[str, Any]]] = {}
    categorical_columns = [
        column for column, role in roles.items()
        if role in {"categorical", "boolean"}
        and 1 < df[column].nunique(dropna=True) <= MAX_CATEGORIES_PER_COLUMN
    ][:MAX_CATEGORICAL_COLUMNS]
    for column in categorical_columns:
        counts = df[column].value_counts(dropna=False).head(MAX_CATEGORIES_PER_COLUMN)
        categorical_distributions[str(column)] = [
            {
                "category": "(missing)" if pd.isna(category) else str(category),
                "count": int(count),
                "percentage": round(float(count) / max(row_count, 1) * 100, 2),
            }
            for category, count in counts.items()
        ]

    group_comparisons: Dict[str, List[Dict[str, Any]]] = {}
    for category_column in categorical_distributions:
        for metric_column in numeric_metrics:
            grouped = (
                df[[category_column, metric_column]]
                .assign(**{metric_column: pd.to_numeric(df[metric_column], errors="coerce")})
                .groupby(category_column, dropna=False)[metric_column]
                .agg(["mean", "count"])
                .dropna(subset=["mean"])
                .sort_values("count", ascending=False)
                .head(MAX_CATEGORIES_PER_COLUMN)
            )
            if len(grouped) < 2:
                continue
            group_comparisons[f"{metric_column} by {category_column}"] = [
                {
                    "category": "(missing)" if pd.isna(category) else str(category),
                    "mean": float(row["mean"]),
                    "count": int(row["count"]),
                }
                for category, row in grouped.iterrows()
            ]
            break

    return {
        "record_count": int(row_count),
        "field_count": int(column_count),
        "missing_cells": missing_cells,
        "missing_percentage": round(missing_cells / max(total_cells, 1) * 100, 2),
        "duplicate_rows": duplicate_rows,
        "numeric_metrics": numeric_metrics,
        "categorical_distributions": categorical_distributions,
        "group_comparisons": group_comparisons,
    }
