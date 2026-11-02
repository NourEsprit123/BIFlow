import pandas as pd
import numpy as np
import re

def _parse_revenue(value):
    """Parse a single Revenue entry into a float.
    Recognized formats:
      * Currency strings like "$1,200.50"
      * Plain numbers possibly with commas (e.g., "850.00")
      * Decimal or integer followed by 'k' (thousand) – e.g., "1.5k", "2.1k", "3k"
      * English word phrases that appear in the data: "five hundred", "one thousand", "quarter million"
    Unrecognizable tokens are converted to ``np.nan``.
    """
    if pd.isna(value):
        return np.nan
    s = str(value).strip()
    if s == "":
        return np.nan
    low = s.lower()

    # 1. Currency format "$1,200.50" – remove $ and commas
    if low.startswith('$'):
        low = low.replace('$', '')
        low = low.replace(',', '')
        try:
            return float(low)
        except ValueError:
            return np.nan

    # 2. Plain numeric with optional commas
    if re.fullmatch(r"[\d,]+(\.\d+)?", low):
        try:
            return float(low.replace(',', ''))
        except ValueError:
            return np.nan

    # 3. Suffix "k" for thousand (e.g., "1.5k", "2k")
    m = re.fullmatch(r"([\d,.]+)k", low)
    if m:
        num_part = m.group(1).replace(',', '')
        try:
            return float(num_part) * 1_000
        except ValueError:
            return np.nan

    # 4. Word‑based numbers – limited to observed phrases
    word_map = {
        "five hundred": 500,
        "one thousand": 1_000,
        "quarter million": 250_000,
    }
    if low in word_map:
        return float(word_map[low])

    # Anything else is considered invalid for this column
    return np.nan

def transform(df: pd.DataFrame) -> pd.DataFrame:
    # Preserve original order and unrelated columns
    # Apply the parser to a copy of the column to avoid chained‑assignment warnings
    parsed_series = df['Revenue'].apply(_parse_revenue)
    # Use pandas nullable Float64 dtype so that NaNs are retained correctly
    df = df.copy()
    df['Revenue'] = pd.Series(parsed_series, dtype='Float64')
    return df