
# ============================================================
# BIFlow - GENERIC DATASET PROFILER
# Profilage descriptif uniquement : aucune modification des donnees
# Formats : CSV, Excel, JSON, Parquet
# ============================================================

import argparse
import json
import os
from pathlib import Path
from datetime import date, datetime

import numpy as np
import pandas as pd

from dotenv import load_dotenv

load_dotenv()


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = BASE_DIR / "reports"

SUPPORTED_FORMATS = {
    ".csv", ".xlsx", ".xls", ".json", ".parquet"
}

MAX_EXAMPLES = 5
MAX_CATEGORIES = 10
MAX_TEXT_LENGTH_SAMPLE = 500


# ============================================================
# JSON SERIALIZATION
# ============================================================

def json_safe(value):
    """Convertit les objets NumPy/Pandas en valeurs JSON compatibles."""

    if value is None:
        return None

    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}

    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]

    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, np.generic):
        return json_safe(value.item())

    if isinstance(value, float) and not np.isfinite(value):
        return None

    if pd.isna(value):
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    return str(value)


# ============================================================
# DATASET LOADING
# ============================================================

def load_dataset(
    file_path,
    has_header=True,
    sheet_name=0,
    encoding=None
):
    """
    Charge un dataset sans modifier les valeurs originales.

    has_header=True  : la premiere ligne contient les noms.
    has_header=False : le fichier n'a pas de ligne d'en-tete.
    """

    path = Path(file_path)

    if not path.is_absolute():
        path = BASE_DIR / path

    if not path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {path}")

    extension = path.suffix.lower()

    if extension not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Format non supporte : {extension}. "
            f"Formats acceptes : {', '.join(sorted(SUPPORTED_FORMATS))}"
        )

    if extension == ".csv":
        options = {
            "header": 0 if has_header else None,
            "low_memory": False,
        }

        if encoding:
            options["encoding"] = encoding

        df = pd.read_csv(path, **options)

    elif extension in {".xlsx", ".xls"}:
        df = pd.read_excel(
            path,
            sheet_name=sheet_name,
            header=0 if has_header else None
        )

    elif extension == ".json":
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)

        if isinstance(data, list):
            df = pd.json_normalize(data)

        elif isinstance(data, dict):
            # Les objets JSON peuvent representer un tableau de donnees
            # ou un objet unique. On traite les deux possibilites.
            if data and all(isinstance(v, list) for v in data.values()):
                try:
                    df = pd.DataFrame(data)
                except ValueError:
                    df = pd.json_normalize(data)
            else:
                df = pd.json_normalize(data)

        else:
            raise ValueError(
                "La racine du JSON doit etre un objet ou une liste."
            )

    else:  # Parquet
        df = pd.read_parquet(path)

    # Les fichiers sans en-tete recoivent des noms techniques.
    # Cela ne change pas le contenu des cellules.
    if extension in {".csv", ".xlsx", ".xls"} and not has_header:
        df.columns = [
            f"column_{i + 1}" for i in range(len(df.columns))
        ]

    # Des noms dupliques peuvent exister dans les fichiers.
    # On les rend uniques pour faciliter le traitement des colonnes.
    unique_columns = []
    seen = {}

    for column in df.columns:
        name = str(column)
        count = seen.get(name, 0)
        seen[name] = count + 1

        if count:
            name = f"{name}_{count + 1}"

        unique_columns.append(name)

    df.columns = unique_columns

    return df, path


# ============================================================
# TYPE DETECTION
# ============================================================



def detect_variable_type(series):
    """
    Détecte le type technique et la nature probable d'une variable
    sans modifier les données originales.

    Les chaînes vides et les chaînes composées d'espaces sont
    considérées comme des valeurs manquantes.
    """

    dtype = str(series.dtype)
    total = len(series)

    # =========================================================
    # 1. DETECTION DES VALEURS MANQUANTES
    # =========================================================

    # Détecter les chaînes vides ou composées d'espaces.
    blank_mask = (
        series.astype("string")
        .str.strip()
        .eq("")
        .fillna(False)
    )

    # Une valeur est manquante si elle est NaN, None ou vide.
    missing_mask = series.isna() | blank_mask

    # Exclure les valeurs manquantes pour la classification.
    non_null = series[~missing_mask]

    missing_count = int(missing_mask.sum())
    non_missing_count = int(non_null.size)

    missing_percentage = (
        round(missing_count / total * 100, 2)
        if total > 0
        else 0.0
    )

    result = {
        "technical_type": dtype,
        "semantic_type": "unknown",
        "classification_method": "dtype",
        "non_missing_count": non_missing_count,
        "missing_count": missing_count,
        "missing_percentage": missing_percentage,
    }

    # =========================================================
    # 2. COLONNE VIDE
    # =========================================================

    if non_null.empty:
        result["semantic_type"] = "empty"
        return result

    # =========================================================
    # 3. TYPE BOOLEEN NATIF
    # =========================================================

    if pd.api.types.is_bool_dtype(series):
        result["semantic_type"] = "boolean"
        return result

    # =========================================================
    # 4. TYPE DATE NATIF
    # =========================================================

    if pd.api.types.is_datetime64_any_dtype(series):
        result["semantic_type"] = "datetime"
        return result

    # =========================================================
    # 5. TYPES NUMERIQUES NATIFS
    # =========================================================

    if pd.api.types.is_numeric_dtype(series):
        name = str(series.name).lower()

        identifier_words = (
            "id",
            "identifier",
            "code",
            "postal",
            "zip",
            "phone",
            "telephone",
            "numsequence",
            "customerid",
            "userid",
            "accountid",
        )

        result["semantic_type"] = (
            "identifier"
            if any(word in name for word in identifier_words)
            else "numeric"
        )

        result["distinct_count"] = int(non_null.nunique())
        return result

    # =========================================================
    # 6. PREPARATION DES COLONNES TEXTE
    # =========================================================

    text = non_null.astype("string").str.strip()
    text = text[text != ""]

    if text.empty:
        result["semantic_type"] = "empty_or_blank"
        return result

    lowered = text.str.lower()

    # =========================================================
    # 7. DETECTION DE VARIABLES BOOLEENNES
    # =========================================================

    boolean_values = {
        "true",
        "false",
        "yes",
        "no",
        "oui",
        "non",
    }

    if lowered.isin(boolean_values).all() and lowered.nunique() <= 2:
        result["semantic_type"] = "boolean_candidate"
        result["classification_method"] = "value_pattern"
        result["distinct_count"] = int(lowered.nunique())
        return result

    # =========================================================
    # 8. DETECTION DE NOMBRES STOCKES EN TEXTE
    # =========================================================

    normalized = (
        text.str.replace("\u00a0", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace(",", ".", regex=False)
    )

    numeric_values = pd.to_numeric(
        normalized,
        errors="coerce"
    )

    numeric_ratio = (
        float(numeric_values.notna().mean())
        if len(numeric_values) > 0
        else 0.0
    )

    if numeric_ratio >= 0.50:
        result["semantic_type"] = "numeric_candidate"
        result["classification_method"] = "value_pattern"

        # Pourcentage calculé uniquement sur les valeurs présentes.
        result["numeric_parse_percentage"] = round(
            numeric_ratio * 100, 2
        )

        result["distinct_count"] = int(
            numeric_values.dropna().nunique()
        )

        result["numeric_parsed_count"] = int(
            numeric_values.notna().sum()
        )

        result["numeric_unparsed_count"] = int(
            numeric_values.isna().sum()
        )

        return result

    # =========================================================
    # 9. DETECTION INDICATIVE DE DATES STOCKEES EN TEXTE
    # =========================================================

    try:
        parsed_dates = pd.to_datetime(
            text.head(200),
            errors="coerce",
            format="mixed"
        )

        date_ratio = float(parsed_dates.notna().mean())

    except (ValueError, TypeError):
        date_ratio = 0.0

    if date_ratio >= 0.90:
        result["semantic_type"] = "datetime_candidate"
        result["classification_method"] = "value_pattern"
        result["date_parse_percentage"] = round(
            date_ratio * 100, 2
        )
        return result

    # =========================================================
    # 10. DETECTION DES VARIABLES CATEGORIELLES ET TEXTUELLES
    # =========================================================

    distinct_count = int(text.nunique())
    distinct_ratio = (
        distinct_count / len(text)
        if len(text) > 0
        else 0.0
    )

    average_length = float(
        text.str.len().mean()
    ) if len(text) > 0 else 0.0

    result["distinct_count"] = distinct_count

    if distinct_count <= 20 or distinct_ratio <= 0.20:
        result["semantic_type"] = "categorical"

    elif average_length > 50:
        result["semantic_type"] = "text"

    else:
        result["semantic_type"] = "text_or_identifier"

    result["classification_method"] = "value_pattern"

    return result



# ============================================================
# NUMERIC DESCRIPTIVE STATISTICS
# ============================================================

def numeric_statistics(series):
    """Statistiques d'une colonne numerique native."""

    values = series.dropna()

    if values.empty:
        return {"available": False, "reason": "Aucune valeur numerique"}

    description = values.describe()

    return {
        "available": True,
        "count": int(values.count()),
        "distinct_count": int(values.nunique()),
        "mean": json_safe(values.mean()),
        "median": json_safe(values.median()),
        "std": json_safe(values.std()),
        "min": json_safe(values.min()),
        "q25": json_safe(description.get("25%")),
        "q50": json_safe(description.get("50%")),
        "q75": json_safe(description.get("75%")),
        "max": json_safe(values.max()),
        "sum": json_safe(values.sum()),
    }



def numeric_candidate_statistics(series):
    import pandas as pd

    # 1. Identifier les valeurs manquantes, y compris les chaînes vides
    original = series.astype("string").str.strip()
    missing_mask = original.isna() | original.eq("")
    non_missing = original[~missing_mask]

    # 2. Convertir temporairement les valeurs non manquantes
    normalized = (
        non_missing
        .str.replace("\u00A0", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace(",", ".", regex=False)
    )

    converted = pd.to_numeric(normalized, errors="coerce")

    # 3. Calculer les indicateurs de conversion
    total_values = len(series)
    missing_count = int(missing_mask.sum())
    non_missing_count = len(non_missing)
    parsed_count = int(converted.notna().sum())
    unparsed_count = non_missing_count - parsed_count

    parse_percentage = (
        parsed_count / non_missing_count * 100
        if non_missing_count > 0
        else 0.0
    )

    # 4. Calculer les statistiques sur les valeurs convertibles
    valid = converted.dropna()

    stats = {
        "available": not valid.empty,
        "total_values": total_values,
        "missing_count": missing_count,
        "non_missing_count": non_missing_count,
        "parsed_count": parsed_count,
        "unparsed_count": unparsed_count,
        "parsed_percentage": round(parse_percentage, 2),
        "distinct_count": int(valid.nunique()),
        "mean": float(valid.mean()) if not valid.empty else None,
        "median": float(valid.median()) if not valid.empty else None,
        "std": float(valid.std()) if not valid.empty else None,
        "min": float(valid.min()) if not valid.empty else None,
        "q25": float(valid.quantile(0.25)) if not valid.empty else None,
        "q75": float(valid.quantile(0.75)) if not valid.empty else None,
        "max": float(valid.max()) if not valid.empty else None,
        "note": (
            "Statistiques exploratoires calculées sur les valeurs "
            "convertibles, sans modifier la colonne originale."
        ),
    }

    return stats



# ============================================================
# CATEGORICAL AND TEXT STATISTICS
# ============================================================

def categorical_statistics(series):
    """Distribution des valeurs d'une colonne categorielle ou textuelle."""

    non_null = series.dropna()
    values = non_null.astype(str)
    frequencies = values.value_counts(dropna=True)

    return {
        "non_missing_count": int(non_null.size),
        "distinct_count": int(non_null.nunique()),
        "most_frequent_values": [
            {
                "value": str(value)[:MAX_TEXT_LENGTH_SAMPLE],
                "count": int(count),
                "percentage_of_non_missing": round(
                    float(count / len(non_null) * 100), 2
                ) if len(non_null) else 0.0,
            }
            for value, count in frequencies.head(MAX_CATEGORIES).items()
        ],
        "examples": [
            str(value)[:MAX_TEXT_LENGTH_SAMPLE]
            for value in values.drop_duplicates().head(MAX_EXAMPLES)
        ],
        "text_length": {
            "min": int(values.str.len().min()) if len(values) else None,
            "mean": round(float(values.str.len().mean()), 2)
            if len(values) else None,
            "max": int(values.str.len().max()) if len(values) else None,
        },
    }


# ============================================================
# DATETIME STATISTICS
# ============================================================

def datetime_statistics(series):
    """Resume temporel pour une colonne de dates reconnue."""

    values = series.dropna()

    if values.empty:
        return {"available": False}

    return {
        "available": True,
        "min": json_safe(values.min()),
        "max": json_safe(values.max()),
        "distinct_count": int(values.nunique()),
    }


def datetime_candidate_statistics(series):
    """Resume indicatif de dates qui sont stockees comme texte."""

    text = series.dropna().astype(str).str.strip()

    if text.empty:
        return {"available": False}

    try:
        parsed = pd.to_datetime(
            text, errors="coerce", format="mixed"
        ).dropna()
    except (ValueError, TypeError):
        return {"available": False}

    if parsed.empty:
        return {"available": False}

    return {
        "available": True,
        "parsed_count": int(parsed.size),
        "min": json_safe(parsed.min()),
        "max": json_safe(parsed.max()),
        "distinct_count": int(parsed.nunique()),
        "note": "Interpretation indicative, sans modification des donnees.",
    }


# ============================================================
# COMPLETE DATASET PROFILING
# ============================================================

def profile_dataset(df, file_path=None, objective=None):
    """Construit un rapport descriptif pour l'ensemble du dataset."""

    rows, columns = df.shape
    column_profiles = {}
    type_counts = {}

    for column in df.columns:
        series = df[column]
        type_info = detect_variable_type(series)
        semantic_type = type_info["semantic_type"]

        type_counts[semantic_type] = type_counts.get(
            semantic_type, 0
        ) + 1

        profile = {
            "name": str(column),
            "type": type_info,
            "examples": [
                json_safe(value)
                for value in series.dropna().head(MAX_EXAMPLES).tolist()
            ],
        }

        if semantic_type == "numeric":
            profile["statistics"] = numeric_statistics(series)

        elif semantic_type == "numeric_candidate":
            profile["statistics"] = numeric_candidate_statistics(series)

        elif semantic_type == "datetime":
            profile["statistics"] = datetime_statistics(series)

        elif semantic_type == "datetime_candidate":
            profile["statistics"] = datetime_candidate_statistics(series)

        elif semantic_type not in {"empty", "empty_or_blank"}:
            profile["statistics"] = categorical_statistics(series)

        else:
            profile["statistics"] = {
                "available": False,
                "reason": "Aucune valeur exploitable"
            }

        column_profiles[str(column)] = profile

    report = {
        "dataset": {
            "file_name": Path(file_path).name if file_path else None,
            "file_path": str(file_path) if file_path else None,
            "format": Path(file_path).suffix.lower() if file_path else None,
            "rows": int(rows),
            "columns": int(columns),
            "memory_usage_bytes": int(
                df.memory_usage(index=True, deep=True).sum()
            ),
            "objective": objective,
        },
        "overview": {
            "semantic_type_counts": type_counts,
            "total_missing_cells": int(df.isna().sum().sum()),
            "missing_cells_percentage": round(
                float(df.isna().sum().sum() / (rows * columns) * 100),
                2
            ) if rows * columns else 0.0,
            "duplicate_row_count_descriptive": int(
                df.duplicated().sum()
            ),
        },
        "columns": column_profiles,
        "limitations": [
            "Le profilage est descriptif et ne modifie pas les donnees.",
            "Les types semantiques sont des estimations et peuvent etre ambigus.",
            "Les nombres et dates detectes dans du texte sont des candidats.",
            "Les valeurs manquantes et les doublons sont decrits sans correction.",
        ],
    }

    return json_safe(report)


# ============================================================
# OPTIONAL GEMINI INTERPRETATION
# ============================================================

def interpret_with_gemini(report, objective=None):
    """
    Gemini explique les statistiques deja calculees.
    Son indisponibilite n'empeche pas la creation du rapport.
    """

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        return {
            "available": False,
            "message": "GEMINI_API_KEY absente. Profilage Python uniquement."
        }

    try:
        from google import genai

        client = genai.Client(api_key=api_key)

        # Envoyer uniquement un resume limite pour eviter un prompt enorme.
        compact_report = {
            "dataset": report["dataset"],
            "overview": report["overview"],
            "columns": {
                name: {
                    "type": info["type"],
                    "statistics": info.get("statistics", {}),
                    "examples": info.get("examples", [])[:3],
                }
                for name, info in list(report["columns"].items())[:60]
            },
        }

        prompt = f"""
Tu es l'analyste de profilage descriptif de BIFlow.

Objectif demande : {objective or "Comprendre la structure du dataset"}.

Analyse le resume JSON ci-dessous et redige en francais :
1. Une synthese de la structure du dataset.
2. Les types de variables dominants.
3. Les principales observations statistiques.
4. Les colonnes qui meritent une exploration ulterieure.
5. Les ambiguities de classification a verifier.

Regles :
- Utilise uniquement les informations fournies.
- N'invente aucune statistique.
- Ne propose pas de corriger ou supprimer des valeurs.
- Ne calcule pas de score de qualite.
- Distingue les types confirmes des types potentiels.
- Si une information est absente, indique-le.

Resume JSON :
{json.dumps(compact_report, ensure_ascii=False, default=str)}
"""

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )

        return {
            "available": True,
            "model": "gemini-2.5-flash",
            "interpretation": response.text or "Aucune interpretation retournee."
        }

    except Exception as exc:
        return {
            "available": False,
            "message": (
                "Interpretation Gemini indisponible. "
                "Le rapport descriptif Python reste disponible."
            ),
            "error": str(exc)[:500],
        }


# ============================================================
# SAVE REPORT
# ============================================================

def save_report(report, file_path):
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    dataset_name = Path(file_path).stem
    report_path = REPORTS_DIR / f"{dataset_name}_profiling_report.json"

    with open(report_path, "w", encoding="utf-8") as file:
        json.dump(
            report,
            file,
            ensure_ascii=False,
            indent=2,
            default=str
        )

    return report_path


# ============================================================
# COMMAND-LINE INTERFACE
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="BIFlow - Profilage descriptif generique de datasets"
    )

    parser.add_argument(
        "file_path",
        help="Chemin du dataset a profiler"
    )

    parser.add_argument(
        "--objective",
        default="Comprendre la structure et les statistiques descriptives.",
        help="Objectif du profilage"
    )

    parser.add_argument(
        "--no-header",
        action="store_true",
        help="Indique que le CSV ou Excel ne contient pas de ligne d'en-tete"
    )

    parser.add_argument(
        "--sheet",
        default="0",
        help="Nom ou index de la feuille Excel (defaut : 0)"
    )

    parser.add_argument(
        "--encoding",
        default=None,
        help="Encodage CSV facultatif, par exemple utf-8 ou latin-1"
    )

    parser.add_argument(
        "--no-gemini",
        action="store_true",
        help="Desactive l'interpretation Gemini"
    )

    args = parser.parse_args()

    sheet_name = args.sheet
    if sheet_name.isdigit():
        sheet_name = int(sheet_name)

    df, resolved_path = load_dataset(
        args.file_path,
        has_header=not args.no_header,
        sheet_name=sheet_name,
        encoding=args.encoding,
    )

    print("\n========== BIFlow : PROFILAGE DESCRIPTIF ==========")
    print(f"Dataset : {resolved_path.name}")
    print(f"Lignes : {df.shape[0]}")
    print(f"Colonnes : {df.shape[1]}")
    print(f"Memoire estimee : {df.memory_usage(deep=True).sum():,} octets")

    print("\nTypes de variables :")
    report = profile_dataset(
        df,
        file_path=resolved_path,
        objective=args.objective,
    )

    for semantic_type, count in report["overview"][
        "semantic_type_counts"
    ].items():
        print(f"  - {semantic_type} : {count}")

    print("\nApercu des colonnes :")
    for name, info in report["columns"].items():
        print(
            f"  - {name} : "
            f"{info['type']['technical_type']} "
            f"-> {info['type']['semantic_type']}"
        )

    if not args.no_gemini:
        print("\nInterpretation Gemini...")
        report["gemini_interpretation"] = interpret_with_gemini(
            report,
            objective=args.objective,
        )

        gemini = report["gemini_interpretation"]
        if gemini.get("available"):
            print(gemini.get("interpretation", ""))
        else:
            print(gemini.get("message", "Gemini indisponible."))

    report_path = save_report(report, resolved_path)

    print(f"\nRapport JSON enregistre : {report_path}")
    print("Profilage termine.")


if __name__ == "__main__":
    main()
