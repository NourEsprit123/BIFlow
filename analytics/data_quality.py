import pandas as pd


def load_dataset(file_path: str) -> pd.DataFrame:
    """
    Charge le dataset CSV.
    """
    return pd.read_csv(file_path)


def detect_missing(df: pd.DataFrame) -> dict:
    """
    Détecte les valeurs manquantes classiques (NaN)
    ainsi que les cellules vides ou contenant uniquement des espaces.
    """

    missing = {}

    for column in df.columns:
        # Valeurs NaN
        nan_count = int(df[column].isna().sum())

        # Valeurs vides / espaces pour les colonnes texte
        empty_count = 0

        if df[column].dtype == "object":
            empty_count = int(
                df[column]
                .fillna("")
                .astype(str)
                .str.strip()
                .eq("")
                .sum()
            )

        total = max(nan_count, empty_count)

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

    duplicate_rows = int(df.duplicated().sum())

    return {
        "count": duplicate_rows,
        "has_duplicates": duplicate_rows > 0
    }


def detect_type_issues(df: pd.DataFrame) -> dict:
    """
    Détecte les colonnes qui semblent avoir un mauvais type.

    Une colonne texte est considérée comme potentiellement
    numérique si la majorité de ses valeurs non vides
    peuvent être converties en nombres.
    """

    issues = {}

    for column in df.columns:

        # On s'intéresse uniquement aux colonnes texte
        if df[column].dtype != "object":
            continue

        series = (
            df[column]
            .dropna()
            .astype(str)
            .str.strip()
        )

        # Ignorer les colonnes complètement vides
        if len(series) == 0:
            continue

        converted = pd.to_numeric(
            series,
            errors="coerce"
        )

        numeric_count = int(converted.notna().sum())
        total_count = len(series)

        numeric_ratio = numeric_count / total_count

        # On détecte maintenant les colonnes
        # qui sont fortement numériques.
        if numeric_ratio >= 0.80:

            issues[column] = {
                "current_type": str(df[column].dtype),
                "expected_type": "numeric",
                "numeric_values": numeric_count,
                "total_values": total_count,
                "numeric_ratio": round(
                    numeric_ratio * 100,
                    2
                ),
                "message": (
                    f"La colonne '{column}' est actuellement "
                    f"de type texte mais {numeric_ratio * 100:.2f}% "
                    "de ses valeurs sont numériques."
                )
            }

    return issues


def detect_inconsistencies(df: pd.DataFrame) -> dict:
    """
    Détecte certaines incohérences dans les données textuelles :

    - espaces inutiles
    - valeurs vides
    - valeurs avec différentes écritures
    """

    inconsistencies = {}

    for column in df.columns:

        if df[column].dtype != "object":
            continue

        series = df[column].dropna().astype(str)

        # Valeurs contenant des espaces au début ou à la fin
        whitespace_count = int(
            (series != series.str.strip()).sum()
        )

        if whitespace_count > 0:
            inconsistencies[column] = {
                "whitespace_values": whitespace_count,
                "message": (
                    f"{whitespace_count} valeur(s) contiennent "
                    "des espaces inutiles."
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

    Le score prend en compte :
    - valeurs manquantes
    - doublons
    - problèmes de types
    - incohérences
    """

    total_cells = df.shape[0] * df.shape[1]

    if total_cells == 0:
        return 0.0

    score = 100.0

    # -------------------------
    # 1. Missing values
    # -------------------------

    missing_ratio = (
        missing_result["total"] / total_cells
    )

    score -= missing_ratio * 100 * 0.40

    # -------------------------
    # 2. Duplicates
    # -------------------------

    duplicate_ratio = (
        duplicate_result["count"] / len(df)
        if len(df) > 0
        else 0
    )

    score -= duplicate_ratio * 100 * 0.25

    # -------------------------
    # 3. Type issues
    # -------------------------

    if len(df.columns) > 0:
        type_ratio = len(type_issues) / len(df.columns)
        score -= type_ratio * 100 * 0.20

    # -------------------------
    # 4. Inconsistencies
    # -------------------------

    if len(df.columns) > 0:
        inconsistency_ratio = (
            len(inconsistencies) / len(df.columns)
        )

        score -= inconsistency_ratio * 100 * 0.15

    # Limiter entre 0 et 100
    score = max(0.0, min(100.0, score))

    return round(score, 2)


def generate_quality_report(file_path: str) -> dict:
    """
    Génère le rapport complet de qualité du dataset.
    """

    df = load_dataset(file_path)

    missing = detect_missing(df)

    duplicates = detect_duplicates(df)

    type_issues = detect_type_issues(df)

    inconsistencies = detect_inconsistencies(df)

    score = calculate_quality_score(
        df,
        missing,
        duplicates,
        type_issues,
        inconsistencies
    )

    return {
        "dataset": file_path,
        "rows": len(df),
        "columns": len(df.columns),

        "quality_score": score,

        "missing_values": missing,

        "duplicates": duplicates,

        "type_issues": type_issues,

        "inconsistencies": inconsistencies,

        "summary": {
            "missing_issues": len(missing["columns"]),
            "duplicate_rows": duplicates["count"],
            "type_issues": len(type_issues),
            "inconsistency_issues": len(inconsistencies)
        }
    }