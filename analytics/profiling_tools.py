
import json
from pathlib import Path

import pandas as pd


def inspect_dataset(path: str) -> dict:
    """Inspecte la structure générale du dataset fourni."""

    df = pd.read_csv(path)

    return {
        "rows": len(df),
        "columns_count": len(df.columns),
        "columns": [
            {
                "name": str(column),
                "type": str(df[column].dtype),
            }
            for column in df.columns
        ],
        "sample": json.loads(
            df.head(5).to_json(
                orient="records",
                date_format="iso",
                force_ascii=False,
            )
        ),
    }


def inspect_column(path: str, column: str) -> dict:
    """Examine une colonne choisie par le LLM."""

    df = pd.read_csv(path)

    if column not in df.columns:
        return {"error": f"Colonne inconnue : {column}"}

    series = df[column]

    return {
        "column": column,
        "dtype": str(series.dtype),
        "missing_count": int(series.isna().sum()),
        "missing_percentage": round(
            float(series.isna().mean() * 100), 2
        ),
        "unique_count": int(series.nunique(dropna=True)),
        "examples": [
            str(value)
            for value in series.dropna().head(10).tolist()
        ],
    }


def analyze_numeric_column(path: str, column: str) -> dict:
    """Calcule les statistiques d'une colonne numérique choisie."""

    df = pd.read_csv(path)

    if column not in df.columns:
        return {"error": f"Colonne inconnue : {column}"}

    series = pd.to_numeric(df[column], errors="coerce")
    valid = series.dropna()

    if valid.empty:
        return {"error": f"Aucune valeur numérique exploitable : {column}"}

    return {
        "column": column,
        "count": int(valid.count()),
        "mean": float(valid.mean()),
        "median": float(valid.median()),
        "std": float(valid.std()) if len(valid) > 1 else 0.0,
        "min": float(valid.min()),
        "max": float(valid.max()),
        "quartiles": {
            "q25": float(valid.quantile(0.25)),
            "q75": float(valid.quantile(0.75)),
        },
    }


def analyze_categorical_column(
    path: str,
    column: str,
    top_n: int = 10,
) -> dict:
    """Examine les catégories et leurs fréquences."""

    df = pd.read_csv(path)

    if column not in df.columns:
        return {"error": f"Colonne inconnue : {column}"}

    counts = df[column].value_counts(
        dropna=False
    ).head(max(1, min(top_n, 30)))

    return {
        "column": column,
        "categories": [
            {
                "value": str(value),
                "count": int(count),
                "percentage": round(
                    float(count / len(df) * 100), 2
                ) if len(df) else 0.0,
            }
            for value, count in counts.items()
        ],
    }


def inspect_missing_values(path: str) -> dict:
    """Recherche les valeurs manquantes dans le dataset."""

    df = pd.read_csv(path)
    missing = df.isna().sum()

    return {
        "rows": len(df),
        "columns_with_missing_values": {
            str(column): int(count)
            for column, count in missing.items()
            if count > 0
        },
        "total_missing": int(missing.sum()),
    }
