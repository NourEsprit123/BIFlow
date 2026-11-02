import pandas as pd
import numpy as np
import re

def _parse_number(text: str) -> float:
    """Parse supported numeric representations into a float.
    Supported formats:
      * Currency strings like "$1,200.00" – symbols and commas are stripped.
      * Plain decimal strings, optionally with leading/trailing whitespace.
      * English number words of the form "<number word> a million" where the number word is a simple integer (e.g., "half a million" -> 0.5 * 1_000_000).
    Returns ``np.nan`` for anything that cannot be parsed.
    """
    if pd.isna(text):
        return np.nan
    s = str(text).strip().lower()
    # Direct currency/decimal parsing
    if s.startswith('$'):
        # Remove $ and commas
        s_clean = re.sub(r'[,$]', '', s)
        try:
            return float(s_clean)
        except ValueError:
            pass
    # Plain numeric (could be like "1200.5")
    try:
        return float(s)
    except ValueError:
        pass
    # English phrase handling – currently only "half a million" is known
    # Map common word multipliers to numeric values
    word_multipliers = {
        "half": 0.5,
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    # Pattern: "<word> a million"
    match = re.fullmatch(r"(\w+) a million", s)
    if match:
        word = match.group(1)
        if word in word_multipliers:
            return word_multipliers[word] * 1_000_000.0
    # If not matched, return NaN (invalid/unrecognized)
    return np.nan

def transform(df: pd.DataFrame) -> pd.DataFrame:
    """Convert the 'MonthlyCost' column to a numeric float representation.
    - Preserves existing NaNs.
    - Recognized currency strings are parsed to their float value.
    - Recognized English phrase "half a million" is interpreted as 500000.
    - All other unparseable strings become NaN.
    The resulting column uses pandas' nullable Float64 dtype to keep NaNs.
    """
    # Apply parser element‑wise
    parsed_series = df['MonthlyCost'].apply(_parse_number)
    # Cast to nullable Float64 to satisfy numeric checks while keeping NaNs
    df['MonthlyCost'] = parsed_series.astype('Float64')
    return df