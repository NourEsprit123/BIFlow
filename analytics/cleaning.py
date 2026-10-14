<<<<<<< Updated upstream
=======
import re
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List

try:
    from word2number import w2n
    HAS_W2N = True
except ImportError:
    HAS_W2N = False


def _parse_number_words(text: str) -> Optional[float]:
    units = {
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
        "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
        "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
        "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
        "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
        "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
        "eighty": 80, "ninety": 90,
    }
    scales = {"hundred": 100, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}
    tokens = text.lower().replace("-", " ").split()
    total = 0.0
    current = 0.0
    matched = False

    for i, token in enumerate(tokens):
        if token == "and":
            continue
        if token in units:
            current += units[token]
            matched = True
        elif token in {"quarter", "half"} and i + 1 < len(tokens) and tokens[i + 1] in scales:
            current += 0.25 if token == "quarter" else 0.5
            matched = True
        elif token in scales:
            scale = scales[token]
            if scale == 100:
                current = max(current, 1) * scale
            else:
                total += max(current, 1) * scale
                current = 0
            matched = True
        else:
            return None

    return total + current if matched else None


def clean_dirty_numeric_series(series: pd.Series, llm_client: Optional[Any] = None) -> pd.Series:
    """
    4-Level Waterfall Pipeline to clean dirty numeric series:
    Level 1: Regex & symbol stripping ($ , € £ whitespace)
    Level 2: word2number conversion ("one thousand" -> 1000)
    Level 3: LLM fallback for complex text numbers ("1.5k")
    Level 4: Safety guardrail (Nonsense becomes NaN)
    """
    missing_values = {"", "nan", "none", "null", "n/a", "na", "?", "missing"}
    parsed_values = []
    failed_indices = []

    for idx, value in series.items():
        text = str(value).strip()
        lowered = text.lower()
        if pd.isna(value) or lowered in missing_values:
            parsed_values.append(np.nan)
            continue

        normalized = re.sub(r"[$€£,\s]", "", text)
        suffix_match = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))([kmb])", normalized, re.IGNORECASE)
        multiplier = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}
        if suffix_match:
            number = float(suffix_match.group(1)) * multiplier[suffix_match.group(2).lower()]
            parsed_values.append(number)
            continue

        try:
            parsed_values.append(float(normalized))
            continue
        except ValueError:
            pass

        try:
            if HAS_W2N:
                parsed_values.append(float(w2n.word_to_num(lowered)))
                continue
        except ValueError:
            pass
        word_number = _parse_number_words(lowered)
        if word_number is not None:
            parsed_values.append(word_number)
            continue

        parsed_values.append(np.nan)
        failed_indices.append(idx)

    cleaned = pd.Series(parsed_values, index=series.index, name=series.name, dtype="float64")

    # Level 3: LLM Fallback (if LLM client provided and there are remaining items)
    if llm_client and failed_indices:
        dirty_samples = series.loc[failed_indices].unique().tolist()[:20]
        prompt = (
            f"You are a Data Cleaning assistant. Convert the following list of dirty text numbers into numeric floats.\n"
            f"If an item is total nonsense (e.g. 'banana', 'unknown'), return null.\n"
            f"Dirty items: {dirty_samples}\n\n"
            f"Return a JSON dictionary mapping exact original string -> numeric float or null.\n"
            f'Example output format: {{"one thousand": 1000.0, "1.5k": 1500.0, "banana": null}}'
        )
        llm_response = llm_client.generate_json(prompt)
        if isinstance(llm_response, dict):
            for idx in failed_indices:
                val_raw = str(series.loc[idx])
                if val_raw in llm_response and llm_response[val_raw] is not None:
                    try:
                        cleaned.loc[idx] = float(llm_response[val_raw])
                    except (ValueError, TypeError):
                        pass

    # Level 4: Guardrail - Any unconvertible value remains NaN safely
    return cleaned


def impute_missing_values(df: pd.DataFrame, imputation_plan: Dict[str, Dict[str, Any]]) -> pd.DataFrame:
    """
    Applies column-specific missing value imputation strategy (median, mean, mode, constant).
    """
    df_clean = df.copy()

    for col, plan in imputation_plan.items():
        if col not in df_clean.columns:
            continue

        is_datetime = pd.api.types.is_datetime64_any_dtype(df_clean[col])
        if not is_datetime and (
            pd.api.types.is_string_dtype(df_clean[col]) or df_clean[col].dtype == "object"
        ):
            missing_mask = (
                df_clean[col].astype("string").str.strip().str.lower()
                .isin(["", "n/a", "null", "none", "?", "missing"])
                .fillna(False)
            )
            df_clean.loc[missing_mask, col] = np.nan

        strategy = plan.get("strategy", "median").lower()
        fill_val = plan.get("value", None)

        if strategy == "median" and pd.api.types.is_numeric_dtype(df_clean[col]):
            median_val = df_clean[col].median()
            df_clean[col] = df_clean[col].fillna(median_val)
        elif strategy == "median" and is_datetime:
            df_clean[col] = df_clean[col].fillna(df_clean[col].median())
        elif strategy == "mean" and pd.api.types.is_numeric_dtype(df_clean[col]):
            mean_val = df_clean[col].mean()
            df_clean[col] = df_clean[col].fillna(mean_val)
        elif strategy == "mean" and is_datetime:
            df_clean[col] = df_clean[col].fillna(df_clean[col].mean())
        elif strategy == "mode":
            mode_series = df_clean[col].mode()
            mode_val = mode_series.iloc[0] if not mode_series.empty else "Unknown"
            df_clean[col] = df_clean[col].fillna(mode_val)
        elif strategy == "constant" and fill_val is not None:
            df_clean[col] = df_clean[col].fillna(fill_val)
        else:
            # Default fallback for objects -> Unknown, for numbers -> median
            if is_datetime:
                mode_series = df_clean[col].mode()
                if not mode_series.empty:
                    df_clean[col] = df_clean[col].fillna(mode_series.iloc[0])
            elif pd.api.types.is_numeric_dtype(df_clean[col]):
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


def treat_outliers(
    df: pd.DataFrame,
    outlier_cols: List[str],
    method: str = "cap",
    bounds: Optional[Dict[str, Dict[str, float]]] = None,
) -> pd.DataFrame:
    """
    Caps numeric outliers at the IQR bounds used by data quality recommendations.
    """
    df_clean = df.copy()
    for col in outlier_cols:
        if col in df_clean.columns and pd.api.types.is_numeric_dtype(df_clean[col]):
            if bounds and col in bounds:
                q_low = bounds[col]["lower_bound"]
                q_high = bounds[col]["upper_bound"]
            else:
                q1 = df_clean[col].quantile(0.25)
                q3 = df_clean[col].quantile(0.75)
                iqr = q3 - q1
                q_low = q1 - 1.5 * iqr
                q_high = q3 + 1.5 * iqr
            df_clean[col] = df_clean[col].clip(lower=q_low, upper=q_high)
    return df_clean
>>>>>>> Stashed changes
