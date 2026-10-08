import pandas as pd

from pandas.api.types import (
    is_numeric_dtype,
    is_string_dtype
)

from analytics.dataset_loader import load_dataset


# ============================================================
# COLUMN ROLE DETECTION
# ============================================================

def detect_column_role(
    df: pd.DataFrame,
    column: str
) -> str:
    """
    Détermine le rôle potentiel d'une colonne.

    Rôles possibles :
    - identifier
    - numerical
    - categorical
    - potential_target
    - text
    - other

    Cette fonction décrit la structure de la colonne.
    Elle ne réalise aucun contrôle de qualité.
    """

    series = df[column]

    # --------------------------------------------------------
    # EMPTY DATASET
    # --------------------------------------------------------

    if len(series) == 0:
        return "other"

    # --------------------------------------------------------
    # NUMERICAL
    # --------------------------------------------------------

    if is_numeric_dtype(series):

        unique_count = series.nunique(
            dropna=True
        )

        total_count = len(series)

        if total_count > 0:

            uniqueness_ratio = (
                unique_count / total_count
            )

            # Une colonne numérique presque entièrement
            # unique peut correspondre à un identifiant.
            #
            # Attention : cette règle reste heuristique.
            if uniqueness_ratio >= 0.95:

                return "identifier"

        return "numerical"

    # --------------------------------------------------------
    # TEXT / CATEGORICAL
    # --------------------------------------------------------

    if is_string_dtype(series):

        non_empty = (
            series
            .dropna()
            .astype(str)
            .str.strip()
        )

        non_empty = non_empty[
            non_empty != ""
        ]

        if len(non_empty) == 0:
            return "text"

        unique_count = non_empty.nunique()

        # Peu de catégories
        if unique_count <= 20:

            # Une variable binaire peut être une
            # cible potentielle, mais ce n'est qu'une
            # suggestion et non une certitude.
            if unique_count == 2:

                return "potential_target"

            return "categorical"

        # Beaucoup de valeurs différentes :
        # probablement du texte libre.
        return "text"

    # --------------------------------------------------------
    # OTHER
    # --------------------------------------------------------

    return "other"


# ============================================================
# TOP VALUES
# ============================================================

def get_top_values(
    df: pd.DataFrame,
    column: str,
    top_n: int = 5
) -> dict:
    """
    Retourne les valeurs les plus fréquentes
    d'une colonne.

    Utilisé uniquement pour décrire les données.
    """

    series = df[column]

    if series.empty:
        return {}

    # On transforme en texte uniquement pour
    # obtenir une représentation homogène.
    series = (
        series
        .dropna()
        .astype(str)
        .str.strip()
    )

    # Les valeurs vides ne sont pas intéressantes
    # pour le résumé des valeurs fréquentes.
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


# ============================================================
# DETAILED COLUMN PROFILE
# ============================================================

def profile_column(
    df: pd.DataFrame,
    column: str
) -> dict:
    """
    Génère un profil descriptif détaillé
    pour une colonne.

    IMPORTANT :
    Cette fonction ne détecte pas les problèmes
    de qualité des données.
    """

    series = df[column]

    # --------------------------------------------------------
    # GENERAL INFORMATION
    # --------------------------------------------------------

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

        "unique": unique_count
    }

    # --------------------------------------------------------
    # NUMERICAL COLUMN
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # CATEGORICAL COLUMN
    # --------------------------------------------------------

    if role in [
        "categorical",
        "potential_target"
    ]:

        result["top_values"] = get_top_values(
            df,
            column,
            top_n=5
        )

    # --------------------------------------------------------
    # TEXT COLUMN
    # --------------------------------------------------------

    if role == "text":

        result["top_values"] = get_top_values(
            df,
            column,
            top_n=5
        )

    return result


# ============================================================
# DATE DETECTION
# ============================================================

def detect_date_columns(
    df: pd.DataFrame,
    threshold: float = 0.8
) -> list:
    """
    Détecte les colonnes contenant probablement des dates.

    Pour éviter de ralentir les gros datasets,
    un maximum de 2000 valeurs est analysé par colonne.

    Cette fonction fait partie du profiling :
    elle cherche à comprendre la structure temporelle
    du dataset.
    """

    date_columns = []

    for column in df.columns:

        series = df[column].dropna()

        if series.empty:
            continue

        # ----------------------------------------------------
        # Déjà au format datetime
        # ----------------------------------------------------

        if pd.api.types.is_datetime64_any_dtype(
            df[column]
        ):

            date_columns.append(column)

            continue

        # ----------------------------------------------------
        # Les colonnes numériques ne sont pas analysées
        # comme dates.
        # ----------------------------------------------------

        if not pd.api.types.is_string_dtype(
            df[column]
        ):

            continue

        # ----------------------------------------------------
        # ECHANTILLON
        # ----------------------------------------------------

        sample = (
            series
            .astype(str)
            .str.strip()
        )

        if len(sample) > 2000:

            sample = sample.head(2000)

        # ----------------------------------------------------
        # CONVERSION
        # ----------------------------------------------------

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


# ============================================================
# MEASURE DETECTION
# ============================================================

def detect_measures(
    df: pd.DataFrame
) -> list:
    """
    Détecte les colonnes numériques pouvant
    être utilisées comme mesures BI.

    Exemple :
    - Quantity
    - Revenue
    - Price
    - MonthlyCharges
    """

    measures = []

    for column in df.columns:

        # ----------------------------------------------------
        # Une mesure doit être numérique.
        # ----------------------------------------------------

        if not is_numeric_dtype(
            df[column]
        ):

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

        # ----------------------------------------------------
        # Les colonnes numériques presque entièrement
        # uniques sont probablement des identifiants.
        # ----------------------------------------------------

        if uniqueness_ratio >= 0.95:

            continue

        measures.append(column)

    return measures


# ============================================================
# DIMENSION DETECTION
# ============================================================

def detect_dimensions(
    df: pd.DataFrame,
    date_columns: list
) -> list:
    """
    Détecte les colonnes pouvant servir
    de dimensions pour l'analyse BI.

    Exemple :
    - Country
    - Region
    - Gender
    - Product Category

    Les dates sont exclues car elles sont déjà
    identifiées séparément.
    """

    dimensions = []

    for column in df.columns:

        # ----------------------------------------------------
        # Les dates sont traitées séparément.
        # ----------------------------------------------------

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


# ============================================================
# MAIN DATA PROFILING
# ============================================================

def profile_dataset(
    file_path: str
) -> dict:
    """
    Analyse automatiquement la structure d'un dataset.

    Le profiling contient uniquement des informations
    descriptives et structurelles.

    Il ne réalise PAS de Data Quality.

    Contenu :
    - nombre de lignes
    - nombre de colonnes
    - noms des colonnes
    - types
    - aperçu
    - cardinalité
    - colonnes numériques
    - colonnes catégorielles
    - statistiques numériques
    - statistiques catégorielles
    - profil détaillé des colonnes
    - rôles potentiels
    - colonnes de dates
    - mesures BI
    - dimensions BI
    """

    # ========================================================
    # LOAD DATASET
    # ========================================================

    df = load_dataset(
        file_path
    )

    # ========================================================
    # GENERAL INFORMATION
    # ========================================================

    rows = len(df)

    columns = len(
        df.columns
    )

    # ========================================================
    # PREVIEW
    # ========================================================

    preview = (
        df
        .head(5)
        .to_dict(
            orient="records"
        )
    )

    # ========================================================
    # COLUMN NAMES
    # ========================================================

    column_names = (
        df.columns.tolist()
    )

    # ========================================================
    # COLUMN TYPES
    # ========================================================

    column_types = {

        column: str(dtype)

        for column, dtype
        in df.dtypes.items()
    }

    # ========================================================
    # UNIQUE VALUES / CARDINALITY
    # ========================================================

    unique_values = {

        column: int(
            df[column]
            .nunique(
                dropna=True
            )
        )

        for column in df.columns
    }

    # ========================================================
    # NUMERICAL COLUMNS
    # ========================================================

    numerical_columns = (
        df
        .select_dtypes(
            include="number"
        )
        .columns
        .tolist()
    )

    # ========================================================
    # CATEGORICAL COLUMNS
    # ========================================================

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

    # ========================================================
    # NUMERICAL STATISTICS
    # ========================================================

    numerical_statistics = {}

    if numerical_columns:

        numerical_statistics = (
            df[numerical_columns]
            .describe()
            .round(2)
            .to_dict()
        )

    # ========================================================
    # CATEGORICAL STATISTICS
    # ========================================================

    categorical_statistics = {}

    for column in categorical_columns:

        categorical_statistics[column] = (
            get_top_values(
                df,
                column,
                top_n=5
            )
        )

    # ========================================================
    # DATE COLUMNS
    # ========================================================

    date_columns = detect_date_columns(
        df
    )

    # ========================================================
    # BI MEASURES
    # ========================================================

    measures = detect_measures(
        df
    )

    # ========================================================
    # BI DIMENSIONS
    # ========================================================

    dimensions = detect_dimensions(
        df,
        date_columns
    )

    # ========================================================
    # DETAILED COLUMN PROFILES
    # ========================================================

    columns_profile = {}

    for column in df.columns:

        columns_profile[column] = (
            profile_column(
                df,
                column
            )
        )

    # ========================================================
    # FINAL PROFILE
    # ========================================================

    return {

        # ----------------------------------------------------
        # GENERAL
        # ----------------------------------------------------

        "dataset": str(
            file_path
        ),

        "rows": rows,

        "columns": columns,

        "column_names": column_names,

        # ----------------------------------------------------
        # STRUCTURE
        # ----------------------------------------------------

        "column_types": column_types,

        "preview": preview,

        "unique_values": unique_values,

        # ----------------------------------------------------
        # COLUMN CATEGORIES
        # ----------------------------------------------------

        "numerical_columns":
            numerical_columns,

        "categorical_columns":
            categorical_columns,

        # ----------------------------------------------------
        # STATISTICS
        # ----------------------------------------------------

        "numerical_statistics":
            numerical_statistics,

        "categorical_statistics":
            categorical_statistics,

        # ----------------------------------------------------
        # DETAILED COLUMN PROFILE
        # ----------------------------------------------------

        "columns_profile":
            columns_profile,

        # ----------------------------------------------------
        # BI STRUCTURE
        # ----------------------------------------------------

        "date_columns":
            date_columns,

        "measures":
            measures,

        "dimensions":
            dimensions
    }