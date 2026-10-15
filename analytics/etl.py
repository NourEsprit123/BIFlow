from typing import Any, Dict, List

import pandas as pd


def validate_transformed_dataset(
    source_df: pd.DataFrame,
    transformed_df: pd.DataFrame,
) -> Dict[str, Any]:
    """Validate that transformed data is loadable without losing its source schema."""
    errors: List[str] = []
    if transformed_df.empty:
        errors.append("The transformed dataset contains no rows.")
    if len(transformed_df.columns) == 0:
        errors.append("The transformed dataset contains no columns.")
    if not transformed_df.columns.is_unique:
        errors.append("Column names must be unique.")
    if any(not str(column).strip() for column in transformed_df.columns):
        errors.append("Column names must not be empty.")
    if list(source_df.columns) != list(transformed_df.columns):
        errors.append("The transformed dataset schema differs from the source schema.")

    missing_cells = int(transformed_df.isna().sum().sum())
    if missing_cells:
        errors.append(f"The transformed dataset still contains {missing_cells} missing cell(s).")

    duplicate_rows = int(transformed_df.duplicated().sum())
    if duplicate_rows:
        errors.append(f"The transformed dataset still contains {duplicate_rows} duplicate row(s).")

    return {
        "valid": not errors,
        "errors": errors,
        "source_rows": len(source_df),
        "output_rows": len(transformed_df),
        "rows_removed": len(source_df) - len(transformed_df),
        "columns": len(transformed_df.columns),
        "missing_cells": missing_cells,
        "duplicate_rows": duplicate_rows,
        "schema_preserved": list(source_df.columns) == list(transformed_df.columns),
    }