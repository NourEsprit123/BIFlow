<<<<<<< Updated upstream
import pandas as pd

from pandas.api.types import (
    is_numeric_dtype,
    is_string_dtype,
)

from analytics.dataset_loader import load_dataset


# ============================================================
# MISSING VALUES
# ============================================================

def detect_missing(df: pd.DataFrame) -> dict:
    """
    Détecte les valeurs manquantes et les chaînes vides.
    """

    missing = {}

    for column in df.columns:
        series = df[column]

        # Valeurs NaN / None
        nan_count = int(series.isna().sum())

        # Chaînes vides ou contenant uniquement des espaces
        empty_count = 0

        if is_string_dtype(series):
            empty_count = int(
                series
                .fillna("")
                .astype(str)
                .str.strip()
                .eq("")
                .sum()
            )

        total = max(nan_count, empty_count)

        if total > 0:
            missing[column] = {
                "count": total,
                "percentage": round(
                    (total / len(df)) * 100,
                    2
                ) if len(df) > 0 else 0
            }

    return {
        "columns": missing,
        "total": sum(
            item["count"]
            for item in missing.values()
        )
    }


# ============================================================
# DUPLICATES
# ============================================================

def detect_duplicates(df: pd.DataFrame) -> dict:
    """
    Détecte les lignes complètement dupliquées.
    """

    duplicate_rows = int(
        df.duplicated().sum()
    )

    percentage = (
        duplicate_rows / len(df) * 100
        if len(df) > 0
        else 0
    )

    return {
        "count": duplicate_rows,
        "percentage": round(
            percentage,
            2
        ),
        "has_duplicates": duplicate_rows > 0
    }


# ============================================================
# TYPE ISSUES
# ============================================================

def detect_type_issues(df: pd.DataFrame) -> dict:
    """
    Détecte les colonnes texte contenant majoritairement
    des valeurs numériques.

    Exemple :
        "120"
        "250"
        "450"

    stockées comme texte.

    Les colonnes déjà numériques (int, float, etc.)
    sont ignorées.
    """

    issues = {}

    for column in df.columns:

        series = df[column]

        # ----------------------------------------------------
        # Ignorer les colonnes déjà numériques
        # ----------------------------------------------------

        if is_numeric_dtype(series):
            continue

        # ----------------------------------------------------
        # Analyser uniquement les colonnes texte
        # ----------------------------------------------------

        if not is_string_dtype(series):
            continue

        cleaned = (
            series
            .dropna()
            .astype(str)
            .str.strip()
        )

        cleaned = cleaned[
            cleaned != ""
        ]

        if len(cleaned) == 0:
            continue

        # ----------------------------------------------------
        # Conversion en numérique
        # ----------------------------------------------------

        converted = pd.to_numeric(
            cleaned,
            errors="coerce"
        )

        numeric_count = int(
            converted.notna().sum()
        )

        total_count = len(cleaned)

        numeric_ratio = (
            numeric_count / total_count
            if total_count > 0
            else 0
        )

        # ----------------------------------------------------
        # Détection du problème
        # ----------------------------------------------------

        if numeric_ratio >= 0.80:

            issues[column] = {
                "current_type": str(
                    series.dtype
                ),
                "expected_type": "numeric",

                "numeric_values": numeric_count,

                "total_values": total_count,

                "numeric_ratio": round(
                    numeric_ratio * 100,
                    2
                ),

                 "message": (
                    f"La colonne '{column}' est stockée comme texte "
                    f"alors que {numeric_ratio * 100:.2f}% de ses valeurs "
                    f"sont numériques."
)

            }

    return issues


# ============================================================
# INCONSISTENCIES
# ============================================================

def detect_inconsistencies(
    df: pd.DataFrame
) -> dict:
    """
    Détecte les espaces inutiles dans les colonnes texte.

    Exemple :
        "France"
        " France"
        "France "
    """

    inconsistencies = {}

    for column in df.columns:

        series = df[column]

        if not (
               pd.api.types.is_object_dtype(series)
               or pd.api.types.is_string_dtype(series)
):
    
            continue

        values = (
            series
            .dropna()
            .astype(str)
        )

        whitespace_count = int(
            (
                values != values.str.strip()
            ).sum()
        )

        if whitespace_count > 0:

            inconsistencies[column] = {
                "whitespace_values": whitespace_count,
                "message": (
                    f"{whitespace_count} valeur(s) "
                    "contiennent des espaces inutiles."
                )
            }

    return inconsistencies


# ============================================================
# OUTLIERS
# ============================================================

def detect_outliers(
    df: pd.DataFrame
) -> dict:
    """
    Détecte les valeurs potentiellement aberrantes
    dans les colonnes numériques avec la méthode IQR.

    Une valeur est considérée comme potentiellement
    aberrante si elle se trouve en dehors de :

        Q1 - 1.5 * IQR

    ou

        Q3 + 1.5 * IQR
    """

    outliers = {}

    for column in df.columns:

        if not is_numeric_dtype(df[column]):
            continue

        series = df[column].dropna()

        # Trop peu de valeurs pour une analyse fiable
        if len(series) < 5:
            continue

        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)

        iqr = q3 - q1

        # Distribution constante
        if iqr == 0:
            continue

        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr

        mask = (
            (series < lower_bound)
            |
            (series > upper_bound)
        )

        count = int(
            mask.sum()
        )

        if count > 0:

            percentage = (
                count / len(series) * 100
            )

            outliers[column] = {
                "count": count,
                "percentage": round(
                    percentage,
                    2
                ),
                "lower_bound": round(
                    float(lower_bound),
                    2
                ),
                "upper_bound": round(
                    float(upper_bound),
                    2
                ),
                "message": (
                    f"{count} valeur(s) "
                    "potentiellement aberrante(s) "
                    "détectée(s)."
                )
            }

    return outliers


# ============================================================
# DATE ISSUES
# ============================================================

def detect_date_issues(
    df: pd.DataFrame
) -> dict:
    """
    Détecte les colonnes texte qui semblent contenir
    des dates mais avec certaines valeurs invalides.
    """

    issues = {}

    for column in df.columns:

        series = df[column]

        if not is_string_dtype(series):
            continue

        values = (
            series
            .dropna()
            .astype(str)
            .str.strip()
        )

        values = values[
            values != ""
        ]

        if len(values) == 0:
            continue

        # Échantillon pour éviter les ralentissements
        # sur les gros datasets.
        sample = values

        if len(sample) > 2000:
            sample = sample.head(2000)

        try:

            converted = pd.to_datetime(
                sample,
                errors="coerce",
                format="mixed"
            )

            valid_ratio = (
                converted.notna().mean()
            )

            # La colonne ressemble suffisamment
            # à une colonne de dates.
            if valid_ratio >= 0.80:

                invalid_count = int(
                    converted.isna().sum()
                )

                if invalid_count > 0:

                    issues[column] = {
                        "invalid_values": invalid_count,
                        "checked_values": len(sample),
                        "message": (
                            f"{invalid_count} valeur(s) "
                            "ne peuvent pas être "
                            "interprétées comme des dates."
                        )
                    }

        except Exception:
            continue

    return issues


# ============================================================
# CONSTANT COLUMNS
# ============================================================

def detect_constant_columns(
    df: pd.DataFrame
) -> dict:
    """
    Détecte les colonnes qui contiennent une seule
    valeur distincte.

    IMPORTANT :
    Une colonne constante n'est PAS considérée comme
    une erreur de qualité.

    Elle est seulement informative.
    """

    constants = {}

    for column in df.columns:

        unique_count = df[column].nunique(
            dropna=True
        )

        if unique_count <= 1:

            value = None

            if len(df) > 0:
                value = df[column].iloc[0]

            constants[column] = {
                "unique_values": unique_count,
                "value": str(value),
                "message": (
                    f"La colonne '{column}' contient "
                    "une seule valeur."
                )
            }

    return constants


# ============================================================
# QUALITY SCORE
# ============================================================

def calculate_quality_score(
    df: pd.DataFrame,
    missing_result: dict,
    duplicate_result: dict,
    type_issues: dict,
    inconsistencies: dict,
    outliers: dict,
    date_issues: dict
) -> float:
    """
    Calcule un score global de qualité entre 0 et 100.

    Les colonnes constantes ne pénalisent PAS le score,
    car elles peuvent être parfaitement normales.

    Pondérations :

        Missing values       : 35%
        Duplicates           : 20%
        Type issues          : 20%
        Inconsistencies      : 10%
        Outliers             : 10%
        Date issues          : 5%
    """

    if df.empty:
        return 0.0

    score = 100.0

    total_cells = (
        df.shape[0] *
        df.shape[1]
    )

    # --------------------------------------------------------
    # Missing values
    # --------------------------------------------------------

    if total_cells > 0:

        missing_ratio = (
            missing_result["total"]
            / total_cells
        )

        score -= (
            missing_ratio *
            100 *
            0.35
        )

    # --------------------------------------------------------
    # Duplicates
    # --------------------------------------------------------

    duplicate_ratio = (
        duplicate_result["count"]
        / len(df)
        if len(df) > 0
        else 0
    )

    score -= (
        duplicate_ratio *
        100 *
        0.20
    )

    # --------------------------------------------------------
    # Type issues
    # --------------------------------------------------------

    if len(df.columns) > 0:

        type_ratio = (
            len(type_issues)
            / len(df.columns)
        )

        score -= (
            type_ratio *
            100 *
            0.20
        )

    # --------------------------------------------------------
    # Inconsistencies
    # --------------------------------------------------------

    if len(df.columns) > 0:

        inconsistency_ratio = (
            len(inconsistencies)
            / len(df.columns)
        )

        score -= (
            inconsistency_ratio *
            100 *
            0.10
        )

    # --------------------------------------------------------
    # Outliers
    # --------------------------------------------------------

    if len(df.columns) > 0:

        outlier_ratio = (
            len(outliers)
            / len(df.columns)
        )

        score -= (
            outlier_ratio *
            100 *
            0.10
        )

    # --------------------------------------------------------
    # Date issues
    # --------------------------------------------------------

    if len(df.columns) > 0:

        date_ratio = (
            len(date_issues)
            / len(df.columns)
        )

        score -= (
            date_ratio *
            100 *
            0.05
        )

    return round(
        max(0.0, min(100.0, score)),
        2
    )


# ============================================================
# ISSUE LEVELS
# ============================================================

def build_issue_levels(
    missing: dict,
    duplicates: dict,
    type_issues: dict,
    inconsistencies: dict,
    outliers: dict,
    date_issues: dict,
    constant_columns: dict
) -> dict:
    """
    Classe les résultats en trois niveaux :

        errors
        warnings
        information

    Cette classification est descriptive.
    Elle ne modifie jamais les données.
    """

    errors = {}
    warnings = {}
    information = {}

    # --------------------------------------------------------
    # ERRORS
    # --------------------------------------------------------

    if missing["total"] > 0:
        errors["missing_values"] = missing

    if type_issues:
        errors["type_issues"] = type_issues

    if date_issues:
        errors["date_issues"] = date_issues

    # --------------------------------------------------------
    # WARNINGS
    # --------------------------------------------------------

    if duplicates["count"] > 0:
        warnings["duplicates"] = duplicates

    if inconsistencies:
        warnings["inconsistencies"] = inconsistencies

    if outliers:
        warnings["outliers"] = outliers

    # --------------------------------------------------------
    # INFORMATION
    # --------------------------------------------------------

    if constant_columns:
        information["constant_columns"] = (
            constant_columns
        )

    return {
        "errors": errors,
        "warnings": warnings,
        "information": information
    }


# ============================================================
# MAIN QUALITY REPORT
# ============================================================

def generate_quality_report(
    file_path: str
) -> dict:
    """
    Génère automatiquement un rapport complet
    de Data Quality.

    Fonctionne avec :

        CSV
        XLSX
        XLS

    Aucun nom de colonne spécifique n'est utilisé.
    """

    # --------------------------------------------------------
    # Load dataset
    # --------------------------------------------------------

    df = load_dataset(file_path)

    # --------------------------------------------------------
    # Quality checks
    # --------------------------------------------------------

    missing = detect_missing(df)

    duplicates = detect_duplicates(df)

    type_issues = detect_type_issues(df)

    inconsistencies = detect_inconsistencies(df)

    outliers = detect_outliers(df)

    date_issues = detect_date_issues(df)

    constant_columns = detect_constant_columns(df)

    # --------------------------------------------------------
    # Quality score
    # --------------------------------------------------------

    score = calculate_quality_score(
        df,
        missing,
        duplicates,
        type_issues,
        inconsistencies,
        outliers,
        date_issues
    )

    # --------------------------------------------------------
    # Issue classification
    # --------------------------------------------------------

    issue_levels = build_issue_levels(
        missing,
        duplicates,
        type_issues,
        inconsistencies,
        outliers,
        date_issues,
        constant_columns
    )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    summary = {
        "missing_issues": len(
            missing["columns"]
        ),

        "missing_values": missing["total"],

        "duplicate_rows": duplicates["count"],

        "type_issues": len(
            type_issues
        ),

        "inconsistency_issues": len(
            inconsistencies
        ),

        "outlier_issues": len(
            outliers
        ),

        "date_issues": len(
            date_issues
        ),

        "constant_columns": len(
            constant_columns
        ),

        "errors": len(
            issue_levels["errors"]
        ),

        "warnings": len(
            issue_levels["warnings"]
        ),

        "information": len(
            issue_levels["information"]
        )
    }

    # --------------------------------------------------------
    # Final report
    # --------------------------------------------------------

    return {
        "dataset": str(file_path),

        "rows": len(df),

        "columns": len(df.columns),

        "quality_score": score,

        # Existing structure kept for compatibility
        "missing_values": missing,

        "duplicates": duplicates,

        "type_issues": type_issues,

        "inconsistencies": inconsistencies,

        "outliers": outliers,

        "date_issues": date_issues,

        "constant_columns": constant_columns,

        # New professional classification
        "issue_levels": issue_levels,

        "summary": summary
=======
import pandas as pd
import numpy as np
from analytics.cleaning import clean_dirty_numeric_series
from typing import Dict, Any, List


def load_dataset(file_path: str) -> pd.DataFrame:
    if file_path.endswith('.xlsx') or file_path.endswith('.xls'):
        return pd.read_excel(file_path)
    elif file_path.endswith('.parquet'):
        return pd.read_parquet(file_path)
    else:
        for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252", "iso-8859-1"):
            try:
                return pd.read_csv(file_path, encoding=encoding)
            except (UnicodeDecodeError, ValueError):
                continue
        return pd.read_csv(file_path, encoding="utf-8", errors="replace")


def detect_missing(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Detects missing values (NaN, null strings, whitespace).
    """
    missing = {}
    for column in df.columns:
        nan_count = int(df[column].isna().sum())
        empty_count = 0
        if pd.api.types.is_string_dtype(df[column]) or df[column].dtype == "object":
            empty_count = int(
                df[column]
                .fillna("")
                .astype(str)
                .str.strip()
                .isin(["", "n/a", "null", "none", "?", "missing"])
                .sum()
            )
        total = max(nan_count, empty_count)
        if total > 0:
            missing[column] = total

    total_cells = df.size
    total_missing_cells = sum(missing.values())
    missing_pct = (total_missing_cells / total_cells * 100) if total_cells > 0 else 0.0

    return {
        "columns": missing,
        "total_missing_cells": total_missing_cells,
        "missing_percentage": round(missing_pct, 2)
    }


def detect_duplicates(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Detects duplicate rows.
    """
    duplicate_rows = int(df.duplicated().sum())
    dup_pct = (duplicate_rows / len(df) * 100) if len(df) > 0 else 0.0
    return {
        "count": duplicate_rows,
        "has_duplicates": duplicate_rows > 0,
        "percentage": round(dup_pct, 2)
    }


def detect_type_mismatches(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Detects multiple type issue categories in object/string columns:
    1. Dirty numeric strings   — numeric data stored as object with symbols/text
    2. Date/time stored as str — date-like strings never parsed as datetime
    3. Boolean stored as text  — Yes/No/True/False stored as object
    4. Pseudo-ID columns       — near-unique string columns that look like IDs
    """
    type_issues = {}
    total_rows = len(df)

    # Regex patterns for date detection
    _date_patterns = [
        r'^\d{4}-\d{2}-\d{2}$',           # 2024-01-15
        r'^\d{2}/\d{2}/\d{4}$',            # 01/15/2024
        r'^\d{2}-\d{2}-\d{4}$',            # 15-01-2024
        r'^\d{4}/\d{2}/\d{2}$',            # 2024/01/15
        r'^\d{1,2} \w+ \d{4}$',            # 15 January 2024
    ]
    _bool_values = {"yes", "no", "true", "false", "y", "n", "1", "0", "oui", "non"}

    for col in df.columns:
        if not (pd.api.types.is_string_dtype(df[col]) or df[col].dtype == "object"):
            continue

        series_non_null = df[col].dropna().astype(str).str.strip()
        if len(series_non_null) < 5:
            continue

        nunique = series_non_null.nunique()

        # ── 1. Dirty numeric strings ──────────────────────────────────────────
        coerced = clean_dirty_numeric_series(series_non_null)
        valid_ratio = coerced.notna().sum() / len(series_non_null)
        plain_numeric = pd.to_numeric(
            series_non_null.str.replace(r'[$€£,\s]', '', regex=True),
            errors='coerce'
        )
        needs_conversion = plain_numeric.isna().any() or series_non_null.str.contains(
            r'[$€£,]|[kmb]$', case=False, regex=True
        ).any()
        if valid_ratio >= 0.5 and needs_conversion:
            dirty_count = int((coerced.isna()).sum())
            type_issues[col] = {
                "valid_numeric_ratio": round(valid_ratio * 100, 2),
                "issue": "Dirty numeric strings (numeric stored as text with symbols/mixed entries)",
                "detected": (
                    f"{dirty_count} unparseable entries out of {len(series_non_null)}; "
                    f"{round(valid_ratio * 100, 1)}% parseable as numbers"
                ),
                "recommendation": "Apply 4-level waterfall cleaning → convert to float/int"
            }
            continue  # Don't double-flag the same column

        # ── 2. Date/time stored as string ─────────────────────────────────────
        sample = series_non_null.head(50)
        date_match_ratio = sum(
            sample.str.match(pat, na=False).mean() for pat in _date_patterns
        )
        if date_match_ratio > 0.6:
            type_issues[col] = {
                "valid_numeric_ratio": round(date_match_ratio * 100, 2),
                "issue": "Date/time values stored as plain text (not parsed as datetime)",
                "detected": f"~{round(date_match_ratio * 100)}% of sampled values match date patterns",
                "recommendation": "Parse with pd.to_datetime() to enable time-series operations"
            }
            continue

        # ── 3. Boolean values stored as text ──────────────────────────────────
        if nunique <= 4:
            lower_vals = set(series_non_null.str.lower().unique())
            bool_overlap = lower_vals & _bool_values
            # Only flag as boolean if ALL values are in the boolean set (no extra categories)
            if len(bool_overlap) >= 2 and lower_vals.issubset(_bool_values):
                type_issues[col] = {
                    "valid_numeric_ratio": 100.0,
                    "issue": "Boolean flag stored as text (Yes/No or True/False as object)",
                    "detected": f"Unique values: {sorted(lower_vals)}",
                    "recommendation": "Map to bool dtype: True/False (saves memory, enables logic ops)"
                }
                continue

        # ── 4. Pseudo-ID / near-unique string column ──────────────────────────
        if total_rows >= 50:
            unique_ratio = nunique / total_rows
            if unique_ratio > 0.95 and not any(
                kw in col.lower() for kw in ["name", "desc", "comment", "note", "address"]
            ):
                type_issues[col] = {
                    "valid_numeric_ratio": round(unique_ratio * 100, 2),
                    "issue": "Pseudo-ID column (near-unique string — likely an identifier or key)",
                    "detected": f"{nunique} unique values out of {total_rows} rows ({round(unique_ratio*100,1)}%)",
                    "recommendation": "Exclude from ML features; consider as join key or primary key"
                }

    return type_issues


def detect_outliers(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Detects statistical outliers in numeric columns using IQR method.
    Returns per-column outlier count and bounds.
    """
    outlier_info = {}
    numeric_cols = df.select_dtypes(include="number").columns

    for col in numeric_cols:
        series = df[col].dropna()
        if len(series) < 10:
            continue
        q1  = series.quantile(0.25)
        q3  = series.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        outlier_mask  = (series < lower) | (series > upper)
        outlier_count = int(outlier_mask.sum())
        if outlier_count > 0:
            outlier_info[col] = {
                "outlier_count": outlier_count,
                "outlier_pct": round(outlier_count / len(series) * 100, 2),
                "lower_bound": round(float(lower), 4),
                "upper_bound": round(float(upper), 4),
            }

    return outlier_info


def calculate_health_scores(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Calculates weighted data health score across Completeness, Validity, Uniqueness, Consistency.
    """
    total_rows = len(df)
    total_cells = df.size if total_rows > 0 else 1

    # 1. Completeness
    missing_info = detect_missing(df)
    completeness = max(0.0, 100.0 - missing_info["missing_percentage"])

    # 2. Uniqueness
    dup_info = detect_duplicates(df)
    uniqueness = max(0.0, 100.0 - dup_info["percentage"])

    # 3. Validity (Type mismatches & invalid entries)
    mismatches = detect_type_mismatches(df)
    validity_penalty = len(mismatches) * 5.0
    validity = max(0.0, 100.0 - validity_penalty)

    # 4. Consistency
    consistency = 95.0 if len(mismatches) == 0 else max(70.0, 100.0 - (len(mismatches) * 10.0))

    # 5. Outliers
    outlier_info = detect_outliers(df)

    # Overall Weighted Health Score
    weighted_score = round(
        (completeness * 0.35) +
        (validity * 0.30) +
        (uniqueness * 0.20) +
        (consistency * 0.15),
        1
    )

    return {
        "overall_health_score": weighted_score,
        "completeness": round(completeness, 1),
        "validity": round(validity, 1),
        "uniqueness": round(uniqueness, 1),
        "consistency": round(consistency, 1),
        "missing_info": missing_info,
        "duplicate_info": dup_info,
        "type_issues": mismatches,
        "outlier_info": outlier_info
>>>>>>> Stashed changes
    }