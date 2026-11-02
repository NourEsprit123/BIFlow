import pandas as pd
import numpy as np
import re
import math

def _word_to_num(text: str) -> float:
    """Parse simple English cardinal numbers (e.g., "five hundred", "one thousand").
    Supports units, teens, tens, and the scale words "hundred", "thousand", "million".
    Returns the numeric value as float. Raises ValueError if parsing fails.
    """
    # Normalise
    text = text.lower().strip()
    if not text:
        raise ValueError("empty string")

    # Tokenise
    tokens = re.split(r"[ -]", text)
    # Dictionaries
    units = {
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9,
    }
    teens = {
        "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
        "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    }
    tens = {
        "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
        "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    }
    scales = {
        "hundred": 100,
        "thousand": 1000,
        "million": 1_000_000,
    }

    total = 0
    current = 0
    for token in tokens:
        if token in units:
            current += units[token]
        elif token in teens:
            current += teens[token]
        elif token in tens:
            current += tens[token]
        elif token in scales:
            # Scale applies to the current chunk
            if current == 0:
                current = 1
            current *= scales[token]
            total += current
            current = 0
        else:
            raise ValueError(f"unrecognised token '{token}' in '{text}'")
    return float(total + current)

def _parse_numeric_suffix(value: str) -> float:
    """Parse strings that contain a numeric part optionally followed by a suffix.
    Supported suffixes (case‑insensitive):
        k → *1e3
        m → *1e6
        b → *1e9
    The numeric part may contain a decimal point.
    """
    match = re.fullmatch(r"(?P<num>[-+]?[0-9]*\.?[0-9]+)(?P<suffix>[kKmMbB]?)", value.strip())
    if not match:
        raise ValueError(f"cannot parse numeric‑suffix format: {value}")
    num = float(match.group('num'))
    suffix = match.group('suffix').lower()
    multiplier = {
        '': 1,
        'k': 1_000,
        'm': 1_000_000,
        'b': 1_000_000_000,
    }.get(suffix, None)
    if multiplier is None:
        raise ValueError(f"unknown suffix '{suffix}' in {value}")
    return num * multiplier

def _clean_currency(value: str) -> str:
    """Remove common currency symbols and thousand separators.
    Currently strips leading '$' and commas.
    """
    return value.replace('$', '').replace(',', '').strip()

def _parse_one(val) -> float:
    """Parse a single cell from the 'amount' column to a float.
    Returns np.nan for missing values, otherwise the numeric float.
    """
    if pd.isna(val):
        return np.nan
    if isinstance(val, (int, float, np.number)):
        return float(val)
    if not isinstance(val, str):
        raise ValueError(f"unexpected non‑string type: {type(val)}")
    s = val.strip()
    # 1. Currency formatted number e.g. $1,200.50
    if s.startswith('$'):
        try:
            return float(_clean_currency(s))
        except ValueError:
            pass  # fall through to other parsers
    # 2. Pure digits (possibly with decimal) e.g. 850
    if re.fullmatch(r"[-+]?[0-9]*\.?[0-9]+", s):
        return float(s)
    # 3. Numeric with suffix e.g. 1.5k, 2k
    try:
        return _parse_numeric_suffix(s)
    except ValueError:
        pass
    # 4. English words e.g. five hundred, one thousand
    try:
        return _word_to_num(s)
    except ValueError:
        pass
    # If none matched, raise – caller will convert to NaN if desired
    raise ValueError(f"unable to parse amount value: {val}")

def transform(df: pd.DataFrame) -> pd.DataFrame:
    """Convert the 'amount' column from heterogeneous string representations to float.
    Keeps row order, index, and all other columns untouched. Missing values remain missing.
    """
    # Work on a copy to avoid side‑effects on the caller's dataframe
    df = df.copy()
    # Apply parsing; errors become NaN to preserve the dataframe shape
    df['amount'] = df['amount'].apply(lambda x: _parse_one(x) if not pd.isna(x) else np.nan)
    return df
