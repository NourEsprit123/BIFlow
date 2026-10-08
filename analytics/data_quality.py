import pandas as pd

from pandas.api.types import is_string_dtype

from analytics.dataset_loader import load_dataset


def detect_missing(df: pd.DataFrame) -> dict:
    """
    Détecte les valeurs manquantes :
    - NaN
    - cellules vides
    - cellules contenant uniquement des espaces
    """

    missing = {}

    for column in df.columns:

        # -----------------------------------------
        # Valeurs NaN
        # -----------------------------------------

        nan_count = int(
            df[column].isna().sum()
        )

        # -----------------------------------------
        # Cellules vides / espaces
        # -----------------------------------------

        empty_count = 0

        if is_string_dtype(df[column]):

            empty_count = int(
                df[column]
                .fillna("")
                .astype(str)
                .str.strip()
                .eq("")
                .sum()
            )

        # -----------------------------------------
        # Total des valeurs manquantes
        # -----------------------------------------
        # max() évite de compter deux fois
        # une même cellule vide représentée
        # à la fois comme NaN et comme vide.

        total = max(
            nan_count,
            empty_count
        )

        if total > 0:

            missing[column] = total

    return {
        "columns": missing,
        "total": sum(missing.values())
    }


def detect_duplicates(df: pd.DataFrame) -> dict:
    """
    Détecte les lignes dupliquées.
    """

    duplicate_rows = int(
        df.duplicated().sum()
    )

    return {
        "count": duplicate_rows,
        "has_duplicates": duplicate_rows > 0
    }


def detect_type_issues(df: pd.DataFrame) -> dict:
    """
    Détecte les colonnes texte qui semblent
    en réalité contenir des données numériques.

    Exemple :
    TotalCharges peut être chargée comme texte
    alors que la majorité de ses valeurs sont numériques.
    """

    issues = {}

    for column in df.columns:

        # -----------------------------------------
        # On s'intéresse uniquement aux colonnes
        # de type texte
        # -----------------------------------------

        if not is_string_dtype(df[column]):
            continue

        # -----------------------------------------
        # Nettoyage des valeurs
        # -----------------------------------------

        series = (
            df[column]
            .dropna()
            .astype(str)
            .str.strip()
        )

        # Retirer les cellules complètement vides
        series = series[
            series != ""
        ]

        if len(series) == 0:
            continue

        # -----------------------------------------
        # Conversion en numérique
        # -----------------------------------------

        converted = pd.to_numeric(
            series,
            errors="coerce"
        )

        numeric_count = int(
            converted.notna().sum()
        )

        total_count = len(series)

        numeric_ratio = (
            numeric_count / total_count
        )

        # -----------------------------------------
        # Si au moins 80 % des valeurs sont
        # numériques, on considère qu'il y a
        # probablement un problème de type.
        # -----------------------------------------

        if numeric_ratio >= 0.80:

            issues[column] = {

                "current_type": str(
                    df[column].dtype
                ),

                "expected_type": "numeric",

                "numeric_values": numeric_count,

                "total_values": total_count,

                "numeric_ratio": round(
                    numeric_ratio * 100,
                    2
                ),

                "message": (
                    f"La colonne '{column}' est actuellement "
                    f"de type texte mais "
                    f"{numeric_ratio * 100:.2f}% "
                    "de ses valeurs sont numériques."
                )
            }

    return issues


def detect_inconsistencies(df: pd.DataFrame) -> dict:
    """
    Détecte certaines incohérences textuelles :
    - espaces inutiles au début ou à la fin
    """

    inconsistencies = {}

    for column in df.columns:

        # -----------------------------------------
        # Vérifier si la colonne est textuelle
        # -----------------------------------------

        if not is_string_dtype(df[column]):
            continue

        series = (
            df[column]
            .dropna()
            .astype(str)
        )

        # -----------------------------------------
        # Détecter les espaces inutiles
        # -----------------------------------------

        whitespace_count = int(
            (
                series
                != series.str.strip()
            ).sum()
        )

        if whitespace_count > 0:

            inconsistencies[column] = {

                "whitespace_values":
                    whitespace_count,

                "message": (
                    f"{whitespace_count} valeur(s) "
                    "contiennent des espaces inutiles."
                )
            }

    return inconsistencies


def calculate_quality_score(
    df: pd.DataFrame,
    missing_result: dict,
    duplicate_result: dict,
    type_issues: dict,
    inconsistencies: dict
) -> float:
    """
    Calcule un score de qualité entre 0 et 100.

    Pondération :
    - Valeurs manquantes : 40 %
    - Doublons : 25 %
    - Problèmes de types : 20 %
    - Incohérences : 15 %
    """

    total_cells = (
        df.shape[0] * df.shape[1]
    )

    if total_cells == 0:
        return 0.0

    score = 100.0

    # =========================================
    # 1. VALEURS MANQUANTES
    # =========================================

    missing_ratio = (
        missing_result["total"]
        / total_cells
    )

    score -= (
        missing_ratio
        * 100
        * 0.40
    )

    # =========================================
    # 2. DOUBLONS
    # =========================================

    duplicate_ratio = (
        duplicate_result["count"]
        / len(df)
        if len(df) > 0
        else 0
    )

    score -= (
        duplicate_ratio
        * 100
        * 0.25
    )

    # =========================================
    # 3. PROBLÈMES DE TYPES
    # =========================================

    if len(df.columns) > 0:

        type_ratio = (
            len(type_issues)
            / len(df.columns)
        )

        score -= (
            type_ratio
            * 100
            * 0.20
        )

    # =========================================
    # 4. INCOHÉRENCES
    # =========================================

    if len(df.columns) > 0:

        inconsistency_ratio = (
            len(inconsistencies)
            / len(df.columns)
        )

        score -= (
            inconsistency_ratio
            * 100
            * 0.15
        )

    # =========================================
    # LIMITER LE SCORE ENTRE 0 ET 100
    # =========================================

    score = max(
        0.0,
        min(100.0, score)
    )

    return round(
        score,
        2
    )


def generate_quality_report(
    file_path: str
) -> dict:
    """
    Génère le rapport complet de qualité
    du dataset.
    """

    # =========================================
    # CHARGEMENT DU DATASET
    # =========================================

    df = load_dataset(
        file_path
    )

    # =========================================
    # ANALYSES
    # =========================================

    missing = detect_missing(
        df
    )

    duplicates = detect_duplicates(
        df
    )

    type_issues = detect_type_issues(
        df
    )

    inconsistencies = detect_inconsistencies(
        df
    )

    # =========================================
    # CALCUL DU SCORE
    # =========================================

    score = calculate_quality_score(
        df,
        missing,
        duplicates,
        type_issues,
        inconsistencies
    )

    # =========================================
    # RAPPORT FINAL
    # =========================================

    return {

        "dataset": str(
            file_path
        ),

        "rows": len(df),

        "columns": len(
            df.columns
        ),

        "quality_score": score,

        "missing_values": missing,

        "duplicates": duplicates,

        "type_issues": type_issues,

        "inconsistencies": inconsistencies,

        "summary": {

            "missing_issues": len(
                missing["columns"]
            ),

            "duplicate_rows":
                duplicates["count"],

            "type_issues":
                len(type_issues),

            "inconsistency_issues":
                len(inconsistencies)
        }
    }