import pandas as pd
import numpy as np
import re

def _parse_monthly_cost(val):
    """Parse a MonthlyCost entry to a numeric float.
    Handles:
      * Currency strings like "$1,200.00" or "$120.00"
      * English phrase "half a million" (interpreted as 500000)
    Returns np.nan for unrecognizable non‑numeric values and preserves existing NaNs.
    """
    if pd.isna(val):
        return np.nan
    s = str(val).strip()
    # Direct phrase handling (case‑insensitive)
    if re.fullmatch(r"half\s+a\s+million", s, flags=re.IGNORECASE):
        return 500000.0
    # Remove leading $ and commas
    s_clean = re.sub(r"[,$]", "", s)
    # After cleaning, attempt float conversion
    try:
        return float(s_clean)
    except ValueError:
        # Anything else is considered invalid
        return np.nan

def transform(df: pd.DataFrame) -> pd.DataFrame:
    # Parse column without chained assignment warnings
    parsed_series = df['MonthlyCost'].apply(_parse_monthly_cost)
    # Use pandas nullable Float64 dtype to keep NaNs compatible with downstream checks
    df = df.copy()
    df['MonthlyCost'] = parsed_series.astype('Float64')
    return df