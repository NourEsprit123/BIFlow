import pandas as pd

from pandas.api.types import (
    is_numeric_dtype,
    is_string_dtype
)

from analytics.dataset_loader import load_dataset


def detect_column_role(
    df: pd.DataFrame,
    column: str
) -> str:
    """
    Détermine automatiquement le rôle potentiel
    d'une colonne.

    Les rôles possibles sont :
    - identifier
    - numerical
    - categorical
    - potential_target
    - text
    """

    series = df[column]

    # =========================================
    # IDENTIFIANT
    # =========================================

    unique_count = series.nunique(
        dropna=True
    )

    total_count = len(series)

    if total_count > 0:

        uniqueness_ratio = (
            unique_count / total_count
        )

        # Une colonne presque entièrement unique
        # peut être un identifiant.
        if uniqueness_ratio >= 0.95:

            return "identifier"

    # =========================================
    # NUMÉRIQUE
    # =========================================

    if is_numeric_dtype(series):

        return "numerical"

    # =========================================
    # TEXTE / CATÉGORIEL
    # =========================================

    if is_string_dtype(series):

        non_empty = (
            series
            .fillna("")
            .astype(str)
            .str.strip()
        )

        non_empty = non_empty[
            non_empty != ""
        ]

        if len(non_empty) == 0:
            return "text"

        unique_count = non_empty.nunique()

        # Nombre de catégories relativement faible
        # => probablement catégoriel
        if unique_count <= 20:

            # Si seulement 2 modalités,
            # cela peut être une cible potentielle.
            if unique_count == 2:

                return "potential_target"

            return "categorical"

        return "text"

    # =========================================
    # AUTRES TYPES
    # =========================================

    return "other"


def get_top_values(
    df: pd.DataFrame,
    column: str,
    top_n: int = 5
) -> dict:
    """
    Retourne les valeurs les plus fréquentes
    d'une colonne catégorielle.
    """

    series = (
        df[column]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    series = series[
        series != ""
    ]

    if series.empty:
        return {}

    value_counts = (
        series
        .value_counts()
        .head(top_n)
    )

    return {
        str(value): int(count)
        for value, count
        in value_counts.items()
    }


def profile_column(
    df: pd.DataFrame,
    column: str
) -> dict:
    """
    Génère un profil détaillé pour une colonne.
    """

    series = df[column]

    # =========================================
    # INFORMATIONS GÉNÉRALES
    # =========================================

    missing_count = int(
        series.isna().sum()
    )

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

    missing_count = max(
        missing_count,
        empty_count
    )

    unique_count = int(
        series.nunique(
            dropna=True
        )
    )

    role = detect_column_role(
        df,
        column
    )

    result = {

        "name": column,

        "type": str(
            series.dtype
        ),

        "role": role,

        "missing": missing_count,

        "missing_percentage": round(
            (
                missing_count
                / len(df)
                * 100
            ),
            2
        ) if len(df) > 0 else 0,

        "unique": unique_count
    }

    # =========================================
    # COLONNE NUMÉRIQUE
    # =========================================

    if is_numeric_dtype(series):

        numeric_series = series.dropna()

        if not numeric_series.empty:

            result["statistics"] = {

                "count": int(
                    numeric_series.count()
                ),

                "mean": round(
                    float(
                        numeric_series.mean()
                    ),
                    2
                ),

                "median": round(
                    float(
                        numeric_series.median()
                    ),
                    2
                ),

                "std": round(
                    float(
                        numeric_series.std()
                    ),
                    2
                ),

                "min": round(
                    float(
                        numeric_series.min()
                    ),
                    2
                ),

                "max": round(
                    float(
                        numeric_series.max()
                    ),
                    2
                ),

                "q25": round(
                    float(
                        numeric_series.quantile(0.25)
                    ),
                    2
                ),

                "q50": round(
                    float(
                        numeric_series.quantile(0.50)
                    ),
                    2
                ),

                "q75": round(
                    float(
                        numeric_series.quantile(0.75)
                    ),
                    2
                )
            }

    # =========================================
    # COLONNE CATÉGORIELLE
    # =========================================

    if role in [
        "categorical",
        "potential_target"
    ]:

        result["top_values"] = get_top_values(
            df,
            column,
            top_n=5
        )

    # =========================================
    # TEXTE
    # =========================================

    if role == "text":

        result["top_values"] = get_top_values(
            df,
            column,
            top_n=5
        )

    return result


def profile_dataset(
    file_path: str
) -> dict:
    """
    Analyse automatiquement un dataset.

    Le profiling contient :

    - informations générales
    - aperçu des données
    - types
    - valeurs manquantes
    - valeurs uniques
    - doublons
    - colonnes numériques
    - colonnes catégorielles
    - statistiques numériques
    - statistiques catégorielles
    - profil détaillé de chaque colonne
    - rôle potentiel des colonnes
    """

    # =========================================
    # CHARGEMENT
    # =========================================

    df = load_dataset(
        file_path
    )


    date_columns = detect_date_columns(df)


    measures = detect_measures(df)

    dimensions = detect_dimensions(
       df,
       date_columns
)

    rows = len(df)

    columns = len(
        df.columns
    )

    # =========================================
    # APERÇU DES DONNÉES
    # =========================================

    preview = (
        df
        .head(5)
        .to_dict(
            orient="records"
        )
    )

    # =========================================
    # TYPES
    # =========================================

    column_types = {
        column: str(dtype)
        for column, dtype
        in df.dtypes.items()
    }

    # =========================================
    # VALEURS MANQUANTES
    # =========================================

    missing_values = {}

    for column in df.columns:

        nan_count = int(
            df[column]
            .isna()
            .sum()
        )

        empty_count = 0

        if is_string_dtype(
            df[column]
        ):

            empty_count = int(
                df[column]
                .fillna("")
                .astype(str)
                .str.strip()
                .eq("")
                .sum()
            )

        missing_count = max(
            nan_count,
            empty_count
        )

        missing_values[column] = (
            missing_count
        )

    total_missing = sum(
        missing_values.values()
    )

    # =========================================
    # VALEURS UNIQUES
    # =========================================

    unique_values = {

        column: int(
            df[column]
            .nunique(
                dropna=True
            )
        )

        for column in df.columns
    }

    # =========================================
    # DOUBLONS
    # =========================================

    duplicate_rows = int(
        df.duplicated().sum()
    )

    # =========================================
    # COLONNES NUMÉRIQUES
    # =========================================

    numerical_columns = (
        df
        .select_dtypes(
            include="number"
        )
        .columns
        .tolist()
    )

    # =========================================
    # COLONNES CATÉGORIELLES
    # =========================================

    categorical_columns = (
        df
        .select_dtypes(
            include=[
                "object",
                "string",
                "category",
                "bool"
            ]
        )
        .columns
        .tolist()
    )

    # =========================================
    # STATISTIQUES NUMÉRIQUES
    # =========================================

    numerical_statistics = {}

    if numerical_columns:

        numerical_statistics = (
            df[numerical_columns]
            .describe()
            .round(2)
            .to_dict()
        )

    # =========================================
    # STATISTIQUES CATÉGORIELLES
    # =========================================

    categorical_statistics = {}

    for column in categorical_columns:

        categorical_statistics[column] = (
            get_top_values(
                df,
                column,
                top_n=5
            )
        )

    # =========================================
    # PROFIL DÉTAILLÉ DES COLONNES
    # =========================================

    columns_profile = {}

    for column in df.columns:

        columns_profile[column] = (
            profile_column(
                df,
                column
            )
        )

    # =========================================
    # RÉSULTAT FINAL
    # =========================================

    return {

        "dataset": str(
            file_path
        ),

        "rows": rows,

        "columns": columns,


        "date_columns": date_columns,
        "measures": measures,
        "dimensions": dimensions,

        "column_names":
            df.columns.tolist(),

        "column_types":
            column_types,

        "preview":
            preview,

        "missing_values":
            missing_values,

        "total_missing":
            total_missing,

        "unique_values":
            unique_values,

        "duplicate_rows":
            duplicate_rows,

        "numerical_columns":
            numerical_columns,

        "categorical_columns":
            categorical_columns,

        "numerical_statistics":
            numerical_statistics,

        "categorical_statistics":
            categorical_statistics,

        "columns_profile":
            columns_profile
    }


def detect_date_columns(df, threshold=0.8):
    """
    Détecte les colonnes contenant des dates.

    Pour éviter de ralentir les gros datasets, on analyse
    au maximum 2000 valeurs par colonne.
    """

    date_columns = []

    for column in df.columns:

        series = df[column].dropna()

        if series.empty:
            continue

        # Déjà reconnu comme datetime
        if pd.api.types.is_datetime64_any_dtype(df[column]):
            date_columns.append(column)
            continue

        # Les colonnes numériques ne sont pas des dates
        if not pd.api.types.is_string_dtype(df[column]):
            continue

        # On ne traite qu'un échantillon
        sample = (
            series
            .astype(str)
            .str.strip()
        )

        if len(sample) > 2000:
            sample = sample.head(2000)

        try:

            converted = pd.to_datetime(
                sample,
                errors="coerce",
                format="mixed"
            )

            ratio = converted.notna().mean()

            if ratio >= threshold:
                date_columns.append(column)

        except Exception:
            continue

    return date_columns


def detect_measures(
    df: pd.DataFrame
) -> list:
    """
    Détecte les colonnes numériques pouvant
    être utilisées comme mesures BI.

    Les identifiants sont exclus.
    """

    measures = []

    for column in df.columns:

        if not is_numeric_dtype(df[column]):
            continue

        unique_count = df[column].nunique(
            dropna=True
        )

        total_count = len(df)

        if total_count == 0:
            continue

        uniqueness_ratio = (
            unique_count / total_count
        )

        # Une colonne presque entièrement unique
        # est probablement un identifiant.
        if uniqueness_ratio >= 0.95:
            continue

        measures.append(column)

    return measures



def detect_dimensions(
    df: pd.DataFrame,
    date_columns: list
) -> list:
    """
    Détecte les colonnes pouvant servir
    de dimensions pour l'analyse BI.
    """

    dimensions = []

    for column in df.columns:

        # Les dates seront traitées séparément.
        if column in date_columns:
            continue

        role = detect_column_role(
            df,
            column
        )

        if role in [
            "categorical",
            "potential_target"
        ]:
            dimensions.append(column)

    return dimensions