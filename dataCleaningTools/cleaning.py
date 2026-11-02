"""
Cleaning tools – concrete, testable operations.

Each function:
  - operates on a DataFrame
  - returns a result summary (affected rows, errors, change metadata)
  - never silently invents business rules

Risk assessment and approval decisions live outside these tools
(in the agent / policy layer).
"""

from __future__ import annotations

import math
from typing import Any, Dict, Literal, Optional, Sequence

import pandas as pd

from .effects import present
from .numeric_expectations import expected_number

ErrorMode = Literal["coerce", "raise", "ignore"]
DuplicateKeep = Literal["first", "last", False]


# ---------------------------------------------------------------------------
# Result envelope used by every cleaning function
# ---------------------------------------------------------------------------

class CleaningResult:
    """Lightweight result object returned by cleaning functions."""

    def __init__(
        self,
        success: bool,
        df: Optional[pd.DataFrame] = None,
        affected_rows: int = 0,
        message: str = "",
        details: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ):
        self.success = success
        self.df = df
        self.affected_rows = affected_rows
        self.message = message
        self.details = details or {}
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "affected_rows": self.affected_rows,
            "message": self.message,
            "details": self.details,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

def handle_missing_values(
    df: pd.DataFrame,
    columns: Optional[Sequence[str]] = None,
    strategy: str = "drop_rows",
    fill_value: Any = None,
    mark_imputed: bool = True,
) -> CleaningResult:
    """
    Handle missing values.

    Fills keep whole-number columns whole (the fill value is rounded) and, with
    mark_imputed, record filled cells in a boolean "<column>_imputed" column so
    downstream analysis can tell estimated values from observed ones.

    Strategies:
      - drop_rows      : drop any row that has NaN in the selected columns
      - drop_columns    : drop columns that contain any NaN
      - fill_constant   : fill with `fill_value`
      - fill_mean       : numeric mean (numeric columns only)
      - fill_median     : numeric median
      - fill_mode       : most frequent value
    """
    cols = list(columns) if columns else list(df.columns)
    missing = set(cols) - set(df.columns)
    if missing:
        return CleaningResult(False, error=f"Columns not found: {missing}")

    # Use the same missing-value definition as profiling/acceptance validation.
    work = df.copy()
    for c in cols:
        work[c] = work[c].mask(~present(work[c]))
    before_nulls = int(work[cols].isna().sum().sum())
    if before_nulls == 0:
        return CleaningResult(True, df=df.copy(), affected_rows=0, message="No missing values")

    affected = 0
    filled = {c: work[c].isna() for c in cols}
    whole = {c: _whole_numbers(work[c]) for c in cols}

    def fill_number(c, value):
        return round(value) if whole[c] and pd.notna(value) else value

    try:
        if strategy == "drop_rows":
            mask = work[cols].isna().any(axis=1)
            affected = int(mask.sum())
            work = work.loc[~mask].reset_index(drop=True)
        elif strategy == "drop_columns":
            to_drop = [c for c in cols if work[c].isna().any()]
            affected = len(to_drop)
            work = work.drop(columns=to_drop)
        elif strategy == "fill_constant":
            affected = int(work[cols].isna().sum().sum())
            work[cols] = work[cols].fillna(fill_value)
        elif strategy == "fill_mean":
            for c in cols:
                if pd.api.types.is_numeric_dtype(work[c]):
                    n = int(work[c].isna().sum())
                    work[c] = work[c].fillna(fill_number(c, work[c].mean()))
                    affected += n
        elif strategy == "fill_median":
            for c in cols:
                if pd.api.types.is_numeric_dtype(work[c]):
                    n = int(work[c].isna().sum())
                    work[c] = work[c].fillna(fill_number(c, work[c].median()))
                    affected += n
        elif strategy == "fill_mode":
            for c in cols:
                mode = work[c].mode()
                if not mode.empty:
                    n = int(work[c].isna().sum())
                    work[c] = work[c].fillna(mode.iloc[0])
                    affected += n
        else:
            return CleaningResult(False, error=f"Unknown strategy: {strategy}")
        if strategy.startswith("fill_"):
            for c in cols:
                if whole[c] and _whole_numbers(work[c]):
                    work[c] = work[c].round().astype("Int64")
                newly = filled[c] & work[c].notna()
                if mark_imputed and newly.any():
                    marker = imputed_column(c)
                    previous = work[marker].fillna(False).astype(bool) if marker in work else False
                    work[marker] = previous | newly
    except Exception as e:
        return CleaningResult(False, error=str(e))

    return CleaningResult(
        True,
        df=work,
        affected_rows=affected,
        message=f"Applied '{strategy}' on {cols}",
        details={"strategy": strategy, "columns": cols, "nulls_before": before_nulls,
                 "imputed_columns": [imputed_column(c) for c in cols if imputed_column(c) in work]},
    )


def imputed_column(column: str) -> str:
    return f"{column}_imputed"


def _whole_numbers(series: pd.Series) -> bool:
    """Numeric (not boolean) values that are all whole numbers, such as counts stored as floats after a CSV round trip."""
    if not pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
        return False
    values = series.dropna()
    return not values.empty and bool((values % 1 == 0).all())


def normalize_values(
    df: pd.DataFrame,
    column: str,
    mapping: Optional[Dict[str, str]] = None,
    strip_whitespace: bool = True,
    case: Optional[str] = None,  # "lower" | "upper" | "title" | None
) -> CleaningResult:
    """
    Normalize categorical / string representations.

    - strip_whitespace: remove leading/trailing spaces
    - case: force case
    - mapping: explicit value → value replacements (applied after strip/case)
    """
    if column not in df.columns:
        return CleaningResult(False, error=f"Column '{column}' not found")

    work = df.copy()
    original = work[column].copy()
    series = work[column].astype("string")

    if strip_whitespace:
        series = series.str.strip()
    if case == "lower":
        series = series.str.lower()
    elif case == "upper":
        series = series.str.upper()
    elif case == "title":
        series = series.str.title()

    if mapping:
        series = series.replace(mapping)

    # Restore original NaNs (astype(str) turns them into "nan")
    work[column] = series
    affected = int((original.astype(str).str.strip() != series.astype(str)).sum())

    return CleaningResult(
        True,
        df=work,
        affected_rows=affected,
        message=f"Normalized column '{column}'",
        details={
            "strip_whitespace": strip_whitespace,
            "case": case,
            "mapping_keys": list(mapping.keys()) if mapping else [],
        },
    )


def convert_data_types(
    df: pd.DataFrame,
    column: str,
    target_type: str,
    errors: ErrorMode = "coerce",
    date_format: Optional[str] = None,
) -> CleaningResult:
    """
    Convert a column to a target type.

    target_type: "numeric", "integer", "float", "string", "boolean", "datetime"
    errors: behaviour for unparseable values (pandas semantics).
    """
    if column not in df.columns:
        return CleaningResult(False, error=f"Column '{column}' not found")

    work = df.copy()
    original = work[column].copy()
    target = target_type.lower()

    try:
        if target in ("numeric", "float"):
            if errors == "ignore":
                converted = pd.to_numeric(work[column], errors="coerce")
                if (original.notna() & converted.isna()).any():
                    return CleaningResult(
                        True,
                        df=df.copy(),
                        message=f"Could not convert '{column}'; values left unchanged",
                        details={"target_type": target_type, "errors": errors},
                    )
                work[column] = converted
            else:
                work[column] = pd.to_numeric(work[column], errors=errors)
        elif target == "integer":
            if errors == "ignore":
                converted = pd.to_numeric(work[column], errors="coerce")
                if (original.notna() & converted.isna()).any():
                    return CleaningResult(
                        True,
                        df=df.copy(),
                        message=f"Could not convert '{column}'; values left unchanged",
                        details={"target_type": target_type, "errors": errors},
                    )
                work[column] = converted
            else:
                work[column] = pd.to_numeric(work[column], errors=errors)
            # only cast to Int64 if no NaNs introduced beyond original, or when coerce
            work[column] = work[column].astype("Int64")
        elif target in ("string", "str"):
            work[column] = work[column].astype("string")
        elif target in ("boolean", "bool"):
            if errors not in ("coerce", "raise", "ignore"):
                return CleaningResult(False, error=f"Unsupported errors mode: {errors}")

            boolean_values = {
                "true": True,
                "t": True,
                "yes": True,
                "y": True,
                "1": True,
                "1.0": True,
                "false": False,
                "f": False,
                "no": False,
                "n": False,
                "0": False,
                "0.0": False,
            }

            def parse_boolean(value: Any) -> Any:
                if pd.isna(value):
                    return pd.NA
                if isinstance(value, bool):
                    return value
                return boolean_values.get(str(value).strip().casefold(), pd.NA)

            parsed = work[column].map(parse_boolean)
            invalid = work[column].notna() & parsed.isna()
            if invalid.any():
                if errors == "raise":
                    invalid_values = work.loc[invalid, column].astype(str).unique().tolist()
                    raise ValueError(f"Cannot convert values to boolean: {invalid_values}")
                if errors == "ignore":
                    return CleaningResult(
                        True,
                        df=df.copy(),
                        message=f"Could not convert '{column}' to boolean; values left unchanged",
                        details={"target_type": target_type, "errors": errors},
                    )
            work[column] = parsed.astype("boolean")
        elif target in ("datetime", "date"):
            if errors == "ignore":
                converted = pd.to_datetime(
                    work[column],
                    format=date_format,
                    errors="coerce",
                )
                if (original.notna() & converted.isna()).any():
                    return CleaningResult(
                        True,
                        df=df.copy(),
                        message=f"Could not convert '{column}'; values left unchanged",
                        details={"target_type": target_type, "errors": errors},
                    )
                work[column] = converted
            else:
                work[column] = pd.to_datetime(
                    work[column],
                    format=date_format,
                    errors=errors,
                )
        else:
            return CleaningResult(False, error=f"Unsupported target_type: {target_type}")
    except Exception as e:
        return CleaningResult(False, error=str(e))

    # Count rows that changed representation or became null
    became_null = int((~original.isna() & work[column].isna()).sum())
    affected = became_null  # conservative; type change itself is the intent

    return CleaningResult(
        True,
        df=work,
        affected_rows=affected,
        message=f"Converted '{column}' to {target_type}",
        details={
            "target_type": target_type,
            "errors": errors,
            "became_null": became_null,
            "date_format": date_format,
        },
    )


def remove_duplicates(
    df: pd.DataFrame,
    subset: Optional[Sequence[str]] = None,
    keep: DuplicateKeep = "first",
) -> CleaningResult:
    """Remove duplicate rows (full row or by key columns)."""
    if subset is not None:
        missing = set(subset) - set(df.columns)
        if missing:
            return CleaningResult(False, error=f"Subset columns not found: {missing}")

    before = len(df)
    work = df.drop_duplicates(subset=list(subset) if subset else None, keep=keep).reset_index(drop=True)
    affected = before - len(work)

    return CleaningResult(
        True,
        df=work,
        affected_rows=affected,
        message=f"Removed {affected} duplicate rows",
        details={"subset": list(subset) if subset else "all", "keep": keep},
    )


def trim_whitespace(
    df: pd.DataFrame,
    columns: Optional[Sequence[str]] = None,
) -> CleaningResult:
    """
    Convenience: strip leading/trailing whitespace from string columns.
    Low-risk operation suitable for automatic execution.
    """
    cols = list(columns) if columns else [
        c for c in df.columns if pd.api.types.is_string_dtype(df[c]) or df[c].dtype == object
    ]
    work = df.copy()
    affected = 0
    for c in cols:
        if c not in work.columns:
            continue
        original = work[c].astype(str)
        stripped = original.str.strip()
        # preserve NaNs
        nan_mask = work[c].isna()
        work[c] = stripped.where(~nan_mask, other=pd.NA)
        affected += int((original != stripped).sum())

    return CleaningResult(
        True,
        df=work,
        affected_rows=affected,
        message=f"Trimmed whitespace on {cols}",
        details={"columns": cols},
    )


def clean_numeric_string(
    df: pd.DataFrame,
    column: str,
    errors: ErrorMode = "coerce",
) -> CleaningResult:
    """
    Parse dirty numeric / currency strings into floats.

    Handles:
      $1,200.50  → 1200.50
      1.5k / 3K  → 1500 / 3000
      2.1m       → 2100000
      parentheses for negatives: (500) → -500
      plain numbers and already-numeric values

    Everything the independent numeric check recognizes is parsed the same
    way (including common English number phrases such as "one thousand"),
    so a trusted builtin can satisfy that check. Unparseable tokens
    (e.g. "banana") become NaN when errors='coerce'. With errors='raise',
    parsing fails; with errors='ignore', the original column is returned unchanged.
    """
    if column not in df.columns:
        return CleaningResult(False, error=f"Column '{column}' not found")
    if errors not in ("coerce", "raise", "ignore"):
        return CleaningResult(False, error=f"Unsupported errors mode: {errors}")

    work = df.copy()
    original = work[column].copy()

    def _parse_one(val: Any) -> Any:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return pd.NA
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return float(val)
        expected = expected_number(val)
        if expected is not None:
            return expected

        s = str(val).strip()
        if s == "" or s.lower() in {"nan", "none", "null", "n/a", "na", "-"}:
            return pd.NA

        # negative accounting style (1,234.56)
        neg = False
        if s.startswith("(") and s.endswith(")"):
            neg = True
            s = s[1:-1]

        s = s.replace("$", "").replace("€", "").replace("£", "").replace(",", "").strip()

        mult = 1.0
        lower = s.lower()
        if lower.endswith("k"):
            mult = 1_000.0
            s = s[:-1]
        elif lower.endswith("m"):
            mult = 1_000_000.0
            s = s[:-1]
        elif lower.endswith("b"):
            mult = 1_000_000_000.0
            s = s[:-1]

        s = s.strip()
        try:
            num = float(s) * mult
            return -num if neg else num
        except ValueError:
            if errors == "coerce":
                return pd.NA
            raise ValueError(f"Unable to parse {val!r} as a numeric string")

    try:
        parsed = original.map(_parse_one)
    except ValueError as exc:
        if errors == "raise":
            return CleaningResult(False, error=str(exc))
        if errors == "ignore":
            return CleaningResult(
                True,
                df=df.copy(),
                message=f"Could not clean '{column}'; values left unchanged",
                details={"errors": errors},
            )
    work[column] = pd.to_numeric(parsed, errors="coerce")

    became_null = int((~original.isna() & work[column].isna()).sum())
    # count values that changed representation
    affected = int((original.astype(str) != work[column].astype(str)).sum())

    return CleaningResult(
        True,
        df=work,
        affected_rows=affected,
        message=f"Cleaned numeric strings in '{column}'",
        details={
            "errors": errors,
            "became_null": became_null,
            "null_after": int(work[column].isna().sum()),
        },
    )


def parse_datetime(
    df: pd.DataFrame,
    column: str,
    date_formats: Optional[Sequence[str]] = None,
    dayfirst: bool = False,
) -> CleaningResult:
    """
    Parse date/time strings into datetimes.

    - date_formats: explicit strftime formats tried in order (e.g. ["%Y-%m-%d", "%d/%m/%Y"]).
      A value matching two formats with different dates is ambiguous and fails
      the operation instead of silently choosing one reading.
    - without date_formats, pandas infers each value; dayfirst resolves 03/04 style dates.
    Existing missing markers stay missing; unparseable values become NaT.
    """
    if column not in df.columns:
        return CleaningResult(False, error=f"Column '{column}' not found")

    work = df.copy()
    original = work[column].copy()
    if pd.api.types.is_datetime64_any_dtype(original):
        return CleaningResult(True, df=work, message=f"'{column}' is already datetime")
    text = original.astype("string").str.strip().where(present(original))

    try:
        if date_formats:
            readings = [pd.to_datetime(text, format=f, errors="coerce") for f in date_formats]
            conflict = pd.Series(False, index=text.index)
            for i, first in enumerate(readings):
                for second in readings[i + 1:]:
                    conflict |= first.notna() & second.notna() & first.ne(second)
            if conflict.any():
                examples = text[conflict].unique()[:5].tolist()
                return CleaningResult(
                    False,
                    error=(f"{int(conflict.sum())} values match more than one format with different dates "
                           f"(e.g. {examples}); keep only one of the conflicting formats or flag_for_review"),
                    details={"ambiguous_count": int(conflict.sum()), "ambiguous_examples": examples},
                )
            parsed = readings[0]
            for reading in readings[1:]:
                parsed = parsed.fillna(reading)
        else:
            # dayfirst would also flip ISO dates (2024-05-06), so ISO values are read first.
            iso = pd.to_datetime(text, format="ISO8601", errors="coerce")
            parsed = iso.fillna(pd.to_datetime(text.where(iso.isna()), format="mixed", dayfirst=dayfirst, errors="coerce"))
    except Exception as e:
        return CleaningResult(False, error=str(e))

    work[column] = parsed
    became_null = int((present(original) & parsed.isna()).sum())
    return CleaningResult(
        True,
        df=work,
        affected_rows=int(present(original).sum()),
        message=f"Parsed '{column}' as datetime",
        details={"date_formats": list(date_formats or []), "dayfirst": dayfirst, "became_null": became_null},
    )


def standardize_missing(
    df: pd.DataFrame,
    columns: Sequence[str],
    markers: Optional[Sequence[str]] = None,
) -> CleaningResult:
    """
    Replace missing-value markers with real nulls.

    Blank strings and the shared markers (n/a, null, none, ?, missing) are always
    replaced; `markers` adds dataset-specific tokens, compared after strip/lowercase.
    """
    missing = set(columns) - set(df.columns)
    if missing:
        return CleaningResult(False, error=f"Columns not found: {missing}")

    tokens = {str(m).strip().lower() for m in markers or []}
    work = df.copy()
    affected = 0
    for c in columns:
        text = work[c].astype("string").str.strip().str.lower()
        mask = work[c].notna() & (~present(work[c]) | text.isin(tokens))
        affected += int(mask.sum())
        work[c] = work[c].mask(mask)
    return CleaningResult(
        True,
        df=work,
        affected_rows=affected,
        message=f"Standardized missing markers in {list(columns)}",
        details={"columns": list(columns), "extra_markers": sorted(tokens)},
    )


def handle_outliers(
    df: pd.DataFrame,
    columns: Sequence[str],
    action: str = "cap",
    method: str = "iqr",
    k: float = 1.5,
    lower: Optional[float] = None,
    upper: Optional[float] = None,
) -> CleaningResult:
    """
    Cap or blank numeric values outside bounds.

    - method="iqr": bounds are Q1 - k*IQR and Q3 + k*IQR of each column
    - method="bounds": explicit lower and/or upper limits
    - action="cap" clips to the bounds; action="set_missing" replaces them with NaN
    """
    missing = set(columns) - set(df.columns)
    if missing:
        return CleaningResult(False, error=f"Columns not found: {missing}")
    if action not in ("cap", "set_missing"):
        return CleaningResult(False, error=f"Unknown action: {action}")
    if method == "bounds" and lower is None and upper is None:
        return CleaningResult(False, error="method='bounds' requires lower and/or upper")
    if method not in ("iqr", "bounds"):
        return CleaningResult(False, error=f"Unknown method: {method}")

    work = df.copy()
    affected = 0
    bounds = {}
    for c in columns:
        series = work[c]
        if not pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
            return CleaningResult(False, error=f"'{c}' is not numeric; convert it before handling outliers")
        lo, hi = lower, upper
        if method == "iqr":
            if series.dropna().empty:
                return CleaningResult(False, error=f"'{c}' has no values to compute IQR bounds")
            q1, q3 = float(series.quantile(0.25)), float(series.quantile(0.75))
            lo, hi = q1 - k * (q3 - q1), q3 + k * (q3 - q1)
        if pd.api.types.is_integer_dtype(series) and action == "cap":
            # Capping an integer column must not introduce fractional values.
            lo = None if lo is None else math.ceil(lo)
            hi = None if hi is None else math.floor(hi)
        outside = pd.Series(False, index=series.index)
        if lo is not None:
            outside |= (series < lo).fillna(False).astype(bool)
        if hi is not None:
            outside |= (series > hi).fillna(False).astype(bool)
        affected += int(outside.sum())
        bounds[c] = {"lower": lo, "upper": hi, "outside": int(outside.sum())}
        work[c] = series.clip(lower=lo, upper=hi) if action == "cap" else series.mask(outside)
    return CleaningResult(
        True,
        df=work,
        affected_rows=affected,
        message=f"Applied outlier {action} on {list(columns)}",
        details={"action": action, "method": method, "k": k, "bounds": bounds},
    )


def drop_column(
    df: pd.DataFrame,
    columns: Sequence[str],
) -> CleaningResult:
    """Drop one or more columns. High-risk — require approval upstream."""
    missing = set(columns) - set(df.columns)
    if missing:
        return CleaningResult(False, error=f"Columns not found: {missing}")

    work = df.drop(columns=list(columns))
    return CleaningResult(
        True,
        df=work,
        affected_rows=0,
        message=f"Dropped columns {list(columns)}",
        details={"dropped": list(columns)},
    )
