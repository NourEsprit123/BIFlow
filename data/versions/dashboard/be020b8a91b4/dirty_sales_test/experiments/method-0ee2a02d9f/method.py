def transform(df):
    import pandas as pd, re, math

    # Mapping for basic number words
    _NUM_WORDS = {
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
        "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
        "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
        "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
        "hundred": 100, "thousand": 1000, "million": 1_000_000
    }

    _FRACTION_WORDS = {
        "quarter": 0.25,
        "half": 0.5,
        "three quarters": 0.75,
        "three quarter": 0.75,
        "three-quarters": 0.75,
        "three‑quarters": 0.75
    }

    def _word_to_number(text: str) -> float | None:
        """Convert simple English number phrases to a float.
        Supports patterns like 'five hundred', 'one thousand', 'quarter million'.
        Returns None if the phrase cannot be parsed.
        """
        text = text.lower().strip()
        # Handle pure fraction words (e.g., 'quarter')
        if text in _FRACTION_WORDS:
            return _FRACTION_WORDS[text]
        # Handle fraction + scale (e.g., 'quarter million')
        for frac_word, frac_val in _FRACTION_WORDS.items():
            if text.startswith(frac_word + " "):
                scale_part = text[len(frac_word):].strip()
                scale_val = _NUM_WORDS.get(scale_part)
                if scale_val:
                    return frac_val * scale_val
        # Tokenise remaining words
        tokens = re.split(r"[ -]", text)
        total = 0
        current = 0
        for token in tokens:
            if token == "":
                continue
            if token not in _NUM_WORDS:
                return None
            val = _NUM_WORDS[token]
            if val == 100:
                # "hundred" multiplies the current chunk
                if current == 0:
                    current = 1
                current *= val
            elif val >= 1000:
                # thousand, million act as multipliers for the accumulated chunk
                if current == 0:
                    current = 1
                total += current * val
                current = 0
            else:
                current += val
        return total + current if (total + current) != 0 else None

    def _parse_value(val):
        if pd.isna(val):
            return val
        if not isinstance(val, str):
            # Unexpected non‑string, attempt numeric conversion directly
            try:
                return float(val)
            except Exception:
                return pd.NA
        s = val.strip()
        # 1. Remove currency symbols and thousand separators
        s = s.replace('$', '').replace(',', '')
        # 2. Direct numeric with optional 'k' suffix
        m = re.fullmatch(r"([+-]?\d*\.?\d+)(k?)", s, flags=re.IGNORECASE)
        if m:
            number = float(m.group(1))
            if m.group(2).lower() == 'k':
                number *= 1_000
            return number
        # 3. Try word‑based representation
        word_num = _word_to_number(s)
        if word_num is not None:
            return float(word_num)
        # 4. If none matched, return NaN (per policy)
        return pd.NA

    # Apply parser element‑wise without chained assignment issues
    parsed_series = df['Revenue'].apply(_parse_value)
    df = df.copy()
    df['Revenue'] = parsed_series.astype('float64')
    return df