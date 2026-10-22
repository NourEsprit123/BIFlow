import pandas as pd
import numpy as np
from typing import Dict, Any, List


def load_dataset(file_path: str) -> pd.DataFrame:
    """
    Loads dataset supporting CSV, Excel (.xlsx), and Parquet formats.
    Auto-detects encoding for CSV files to handle non-UTF-8 sources (e.g. Excel exports).
    """
    if file_path.endswith('.xlsx') or file_path.endswith('.xls'):
        return pd.read_excel(file_path)
    elif file_path.endswith('.parquet'):
        return pd.read_parquet(file_path)
    else:
        # Try UTF-8 first, then fall back through common encodings
        for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252", "iso-8859-1"):
            try:
                return pd.read_csv(file_path, encoding=encoding)
            except (UnicodeDecodeError, ValueError):
                continue
        # Last resort: ignore undecodable bytes
        return pd.read_csv(file_path, encoding="utf-8", errors="replace")


def infer_column_roles(df: pd.DataFrame) -> Dict[str, str]:
    """
    Infers semantic column roles based on cardinality, types, and column names.
    Roles: 'primary_key', 'categorical', 'continuous_numeric', 'timestamp', 'boolean'
    """
    roles = {}
    total_rows = len(df)

    for col in df.columns:
        series = df[col]
        nunique = series.nunique(dropna=True)
        dtype_str = str(series.dtype)

        # ID / Primary key check
        if nunique == total_rows and total_rows > 10 and ('id' in col.lower() or 'key' in col.lower() or dtype_str == 'object'):
            roles[col] = 'primary_key'
        elif pd.api.types.is_datetime64_any_dtype(series) or 'date' in col.lower() or 'time' in col.lower():
            roles[col] = 'timestamp'
        elif nunique == 2 and (set(series.dropna().unique()).issubset({0, 1, '0', '1', True, False, 'Yes', 'No', 'yes', 'no'})):
            roles[col] = 'boolean'
        elif pd.api.types.is_numeric_dtype(series):
            if nunique < 10 and nunique / max(total_rows, 1) < 0.05:
                roles[col] = 'categorical'
            else:
                roles[col] = 'continuous_numeric'
        else:
            roles[col] = 'categorical'

    return roles


def profile_dataset(file_path: str) -> Dict[str, Any]:
    """
    Analyzes the structure, schema, cardinalities, and numerical distributions of a dataset.
    """
    df = load_dataset(file_path)

    rows = len(df)
    columns = len(df.columns)

    missing_values = {col: int(df[col].isna().sum()) for col in df.columns}
    total_missing = sum(missing_values.values())
    duplicate_rows = int(df.duplicated().sum())

    column_types = {col: str(dtype) for col, dtype in df.dtypes.items()}
    unique_values = {col: int(df[col].nunique(dropna=True)) for col in df.columns}

    numerical_columns = df.select_dtypes(include="number").columns.tolist()
    categorical_columns = df.select_dtypes(include=["object", "category", "bool"]).columns.tolist()

    numerical_statistics = {}
    if numerical_columns:
        numerical_statistics = df[numerical_columns].describe().round(2).to_dict()

    column_roles = infer_column_roles(df)

    return {
        "rows": rows,
        "columns": columns,
        "column_names": df.columns.tolist(),
        "column_types": column_types,
        "column_roles": column_roles,
        "missing_values": missing_values,
        "total_missing": total_missing,
        "duplicate_rows": duplicate_rows,
        "unique_values": unique_values,
        "numerical_columns": numerical_columns,
        "categorical_columns": categorical_columns,
        "numerical_statistics": numerical_statistics,
    }