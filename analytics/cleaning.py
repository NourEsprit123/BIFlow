import json
import re
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List

NUMERIC_LLM_BATCH_SIZE = 5
NUMERIC_LLM_MAX_OUTPUT_TOKENS = 150

try:
    from word2number import w2n
    HAS_W2N = True
except ImportError:
    HAS_W2N = False


def clean_dirty_numeric_series(series: pd.Series, llm_client: Optional[Any] = None) -> pd.Series:
    """
    4-Level Waterfall Pipeline to clean dirty numeric series:
    Level 1: Regex & symbol stripping ($ , € £ whitespace)
    Level 2: word2number conversion ("one thousand" -> 1000)
    Level 3: LLM fallback for complex text numbers ("1.5k")
    Level 4: Safety guardrail (Nonsense becomes NaN)
    """
    # Convert series to string
    cleaned_str = series.astype(str).str.strip()

    # Level 1: Regex & symbol stripping
    # Remove currency symbols, commas, and trailing whitespace
    level1_str = cleaned_str.str.replace(r'[$,€,£,\s]', '', regex=True)
    level1_num = pd.to_numeric(level1_str, errors='coerce')

    # Find indices that failed Level 1
    failed_mask = level1_num.isna() & (cleaned_str != '') & (~cleaned_str.str.lower().isin(['nan', 'none', 'null', 'n/a', '?']))
    failed_indices = series[failed_mask].index.tolist()

    if not failed_indices:
        return level1_num

    # Level 2: word2number conversion for failed items
    if HAS_W2N:
        for idx in failed_indices:
            val_str = str(series.loc[idx]).strip().lower()
            try:
                converted = w2n.word_to_num(val_str)
                level1_num.loc[idx] = float(converted)
                failed_mask.loc[idx] = False
            except ValueError:
                pass

    # Re-evaluate failed items
    remaining_failed_indices = level1_num.isna() & (cleaned_str != '') & (~cleaned_str.str.lower().isin(['nan', 'none', 'null', 'n/a', '?']))
    remaining_indices = series[remaining_failed_indices].index.tolist()

    # Level 3: LLM fallback in small batches to keep JSON responses within provider limits.
    if llm_client and remaining_indices:
        dirty_values = list(dict.fromkeys(
            str(value) for value in series.loc[remaining_indices].tolist()
        ))
        for start in range(0, len(dirty_values), NUMERIC_LLM_BATCH_SIZE):
            dirty_batch = dirty_values[start:start + NUMERIC_LLM_BATCH_SIZE]
            prompt = (
                "Convert each dirty text number to a numeric float. Return null for "
                "nonsense. Return only a JSON object mapping each exact input string "
                "to a number or null. Include every input key exactly once. "
                f"Inputs: {json.dumps(dirty_batch, ensure_ascii=False)}"
            )
            llm_response = llm_client.generate_json(
                prompt,
                system_prompt=(
                    "You convert text representations of numbers. Return only the "
                    "requested compact JSON object; do not add explanations."
                ),
                max_output_tokens=NUMERIC_LLM_MAX_OUTPUT_TOKENS,
            )
            if isinstance(llm_response, dict):
                for idx in remaining_indices:
                    val_raw = str(series.loc[idx])
                    if val_raw not in dirty_batch:
                        continue
                    converted_value = llm_response.get(val_raw)
                    if converted_value is not None:
                        try:
                            level1_num.loc[idx] = float(converted_value)
                        except (ValueError, TypeError):
                            pass

    # Level 4: Guardrail - Any unconvertible value remains NaN safely
    return level1_num


def impute_missing_values(df: pd.DataFrame, imputation_plan: Dict[str, Dict[str, Any]]) -> pd.DataFrame:
    """
    Applies column-specific missing value imputation strategy (median, mean, mode, constant).
    """
    df_clean = df.copy()

    for col, plan in imputation_plan.items():
        if col not in df_clean.columns:
            continue

        if pd.api.types.is_string_dtype(df_clean[col]) or df_clean[col].dtype == "object":
            missing_mask = df_clean[col].astype("string").str.strip().str.lower().isin(
                ["", "n/a", "null", "none", "?", "missing"]
            )
            df_clean.loc[missing_mask, col] = np.nan

        strategy = plan.get("strategy", "median").lower()
        fill_val = plan.get("value", None)

        if strategy == "median" and pd.api.types.is_numeric_dtype(df_clean[col]):
            median_val = df_clean[col].median()
            df_clean[col] = df_clean[col].fillna(median_val)
        elif strategy == "mean" and pd.api.types.is_numeric_dtype(df_clean[col]):
            mean_val = df_clean[col].mean()
            df_clean[col] = df_clean[col].fillna(mean_val)
        elif strategy == "mode":
            mode_series = df_clean[col].mode()
            mode_val = mode_series.iloc[0] if not mode_series.empty else "Unknown"
            df_clean[col] = df_clean[col].fillna(mode_val)
        elif strategy == "constant" and fill_val is not None:
            df_clean[col] = df_clean[col].fillna(fill_val)
        else:
            # Default fallback for objects -> Unknown, for numbers -> median
            if pd.api.types.is_numeric_dtype(df_clean[col]):
                df_clean[col] = df_clean[col].fillna(df_clean[col].median())
            else:
                df_clean[col] = df_clean[col].fillna("Unknown")

    return df_clean


def standardize_categorical_synonyms(df: pd.DataFrame, synonym_mappings: Dict[str, Dict[str, str]]) -> pd.DataFrame:
    """
    Standardizes categorical text values using canonical replacement dictionaries.
    """
    df_clean = df.copy()
    for col, mapping in synonym_mappings.items():
        if col in df_clean.columns and isinstance(mapping, dict):
            df_clean[col] = df_clean[col].replace(mapping)
    return df_clean


def treat_outliers(df: pd.DataFrame, outlier_cols: List[str], method: str = "cap") -> pd.DataFrame:
    """
    Caps numeric outliers at 1st and 99th percentiles (Winsorizing).
    """
    df_clean = df.copy()
    for col in outlier_cols:
        if col in df_clean.columns and pd.api.types.is_numeric_dtype(df_clean[col]):
            q_low = df_clean[col].quantile(0.01)
            q_high = df_clean[col].quantile(0.99)
            df_clean[col] = df_clean[col].clip(lower=q_low, upper=q_high)
    return df_clean
