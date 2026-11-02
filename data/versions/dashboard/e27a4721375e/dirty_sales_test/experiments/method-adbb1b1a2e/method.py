import pandas as pd
import numpy as np
import re

def _word_number_to_float(text: str) -> float | None:
    """Convert simple English number words to a float.
    Supports patterns like:
        'five hundred', 'one thousand', 'quarter million'
    Returns None if parsing fails.
    """
    text = text.lower().strip()
    # Mapping for basic numbers
    units = {
        "zero": 0,
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
        "eleven": 11,
        "twelve": 12,
        "thirteen": 13,
        "fourteen": 14,
        "fifteen": 15,
        "sixteen": 16,
        "seventeen": 17,
        "eighteen": 18,
        "nineteen": 19,
        "twenty": 20,
        "thirty": 30,
        "forty": 40,
        "fifty": 50,
        "sixty": 60,
        "seventy": 70,
        "eighty": 80,
        "ninety": 90,
    }
    multipliers = {
        "hundred": 1e2,
        "thousand": 1e3,
        "million": 1e6,
        "billion": 1e9,
    }
    # Special fractional words
    fractions = {"quarter": 0.25, "half": 0.5, "third": 1/3, "three quarters": 0.75}
    # Direct fraction + multiplier e.g., 'quarter million'
    parts = text.split()
    if len(parts) == 2 and parts[0] in fractions and parts[1] in multipliers:
        return fractions[parts[0]] * multipliers[parts[1]]
    # Simple composition like 'five hundred' or 'one thousand'
    total = 0
    current = 0
    for token in parts:
        if token in units:
            current += units[token]
        elif token in multipliers:
            # Apply multiplier to the current chunk; if current is zero, assume 1
            if current == 0:
                current = 1
            total += current * multipliers[token]
            current = 0
        else:
            return None
    total += current
    return total if total != 0 else None

def _parse_single(val) -> float:
    """Parse a single Revenue entry into a float or np.nan.
    Handles:
    - Currency strings like "$1,200.50"
    - Plain numbers with optional commas
    - Decimal numbers with a trailing 'k' (e.g., '1.5k', '3k')
    - English word numbers (e.g., 'five hundred')
    Anything unrecognised becomes np.nan.
    """
    if pd.isna(val):
        return np.nan
    s = str(val).strip()
    if s == "":
        return np.nan
    # 1. Currency / commas
    if s.startswith('$'):
        s = s.replace('$', '')
    s = s.replace(',', '')
    # 2. k suffix (e.g., 1.5k, 3k)
    m = re.fullmatch(r"(?P<num>\d+(?:\.\d+)?)k", s, re.IGNORECASE)
    if m:
        try:
            return float(m.group('num')) * 1_000
        except ValueError:
            return np.nan
    # 3. Plain numeric string
    if re.fullmatch(r"-?\d+(?:\.\d+)?", s):
        try:
            return float(s)
        except ValueError:
            return np.nan
    # 4. Word numbers
    word_val = _word_number_to_float(s)
    if word_val is not None:
        return float(word_val)
    # 5. Anything else is invalid
    return np.nan

def transform(df):
    # Preserve original order and unrelated columns.
    # Apply parser to Revenue column and store result as float64 (np.nan for missing/invalid).
    parsed_series = df['Revenue'].apply(_parse_single)
    df = df.copy()
    df.loc[:, 'Revenue'] = parsed_series.astype('float64')
    return df