"""Independent acceptance oracle for a bounded set of numeric representations.

This validates results; it never cleans a dataset or executes generated code.
Unrecognized strings have no expected value and remain eligible for NaN coercion.
"""
from functools import lru_cache
import math
import numbers
import re

import pandas as pd

SMALL = dict(zip("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(), range(20)))
TENS = dict(zip("twenty thirty forty fifty sixty seventy eighty ninety".split(), range(20, 100, 10)))
SCALES = {"thousand": 1000, "million": 1000000, "billion": 1000000000}
NUMBER = r"[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?"


def _small_group(words):
    if len(words) == 1:
        return SMALL.get(words[0], TENS.get(words[0]))
    if len(words) == 2 and words[0] in TENS and 0 < SMALL.get(words[1], 0) < 10:
        return TENS[words[0]] + SMALL[words[1]]
    return None


def _group(words):
    if len(words) >= 2 and words[1] == "hundred" and words[0] in {"a", *list(SMALL)[1:10]}:
        head = 100 if words[0] == "a" else SMALL[words[0]] * 100
        rest = words[2:]
        if rest[:1] == ["and"]:
            rest = rest[1:]
            if not rest:
                return None
        tail = _small_group(rest) if rest else 0
        return head + tail if tail is not None else None
    return _small_group(words)


@lru_cache(maxsize=10000)
def _text_number(text):
    text = text.strip().lower()
    if len(text) > 200:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()
    # Strip one conventional currency symbol, never infer exchange rates.
    if text[:1] in {"$", "€", "£"}:
        text = text[1:].strip()
    sign = -1 if negative else 1
    match = re.fullmatch(rf"({NUMBER})\s*(k|m|b|hundred|thousand|million|billion)?", text)
    if match:
        multiplier = {None: 1, "k": 1000, "m": 1000000, "b": 1000000000, "hundred": 100, **SCALES}[match[2]]
        value = float(match[1].replace(",", "")) * multiplier * sign
        return value if math.isfinite(value) else None
    fraction = re.fullmatch(r"(half|quarter)(?: of)?(?: a)? (hundred|thousand|million|billion)", text)
    if fraction:
        return sign * ({"half": 0.5, "quarter": 0.25}[fraction[1]]) * {"hundred": 100, **SCALES}[fraction[2]]
    if text.startswith(("minus ", "negative ")):
        sign *= -1
        text = text.split(" ", 1)[1]
    words = text.replace("-", " ").split()
    total, start, last_scale = 0, 0, float("inf")
    for index, word in enumerate(words):
        if word not in SCALES:
            continue
        scale = SCALES[word]
        group_words = words[start:index]
        group = 1 if group_words == ["a"] else _group(group_words)
        if group is None or scale >= last_scale:
            return None
        total += group * scale
        start, last_scale = index + 1, scale
    rest = words[start:]
    if total and rest[:1] == ["and"]:
        rest = rest[1:]
        if not rest:
            return None
    tail = _group(rest) if rest else (0 if total else None)
    return sign * (total + tail) if tail is not None else None


def expected_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        return _text_number(value)
    if isinstance(value, numbers.Real):
        value = float(value)
        return value if math.isfinite(value) else None
    return None


def numeric_rules(before, after, columns):
    """Check every recognized source cell, including rare formats and magnitudes."""
    rules = []
    for column in columns:
        if column not in before or column not in after or len(before) != len(after):
            continue
        checked, mismatches = 0, []
        for position, (old, new) in enumerate(zip(before[column], after[column])):
            expected = expected_number(old)
            if expected is None:
                continue
            checked += 1
            try:
                correct = not pd.isna(new) and math.isclose(float(new), expected, rel_tol=1e-12, abs_tol=1e-9)
            except (TypeError, ValueError, OverflowError):
                correct = False
            if not correct:
                mismatches.append({"row_position": position, "row_index": str(before.index[position]),
                    "column": column, "before": str(old), "expected": expected,
                    "actual": None if pd.isna(new) else str(new)})
        if checked:
            rules.append({"rule_name": f"expected:numeric_values:{column}", "passed": not mismatches,
                "message": f"Preserve the numeric meaning of {checked} recognized source values; {len(mismatches)} mismatches",
                "checked_values": checked, "mismatches": mismatches})
    return rules
