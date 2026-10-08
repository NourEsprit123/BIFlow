import pandas as pd


def load_dataset(file_path: str) -> pd.DataFrame:
    """
    Charge un dataset CSV.
    """
    return pd.read_csv(file_path)


def profile_dataset(file_path: str) -> dict:
    """
    Analyse la structure générale d'un dataset.

    Retourne un dictionnaire contenant :
    - nombre de lignes
    - nombre de colonnes
    - colonnes
    - types
    - valeurs manquantes
    - valeurs uniques
    - doublons
    - statistiques numériques
    """

    df = load_dataset(file_path)

    # Informations générales
    rows = len(df)
    columns = len(df.columns)

    # Valeurs manquantes
    missing_values = df.isna().sum()

    # Nombre total de cellules manquantes
    total_missing = int(missing_values.sum())

    # Doublons
    duplicate_rows = int(df.duplicated().sum())

    # Types de colonnes
    column_types = {
        column: str(dtype)
        for column, dtype in df.dtypes.items()
    }

    # Valeurs uniques par colonne
    unique_values = {
        column: int(df[column].nunique(dropna=True))
        for column in df.columns
    }

    # Colonnes numériques
    numerical_columns = df.select_dtypes(
        include="number"
    ).columns.tolist()

    # Colonnes catégorielles
    categorical_columns = df.select_dtypes(
        include=["object", "category", "bool"]
    ).columns.tolist()

    # Statistiques numériques
    numerical_statistics = {}

    if numerical_columns:
        numerical_statistics = (
            df[numerical_columns]
            .describe()
            .round(2)
            .to_dict()
        )

    return {
        "rows": rows,
        "columns": columns,
        "column_names": df.columns.tolist(),
        "column_types": column_types,
        "missing_values": {
            column: int(value)
            for column, value in missing_values.items()
        },
        "total_missing": total_missing,
        "duplicate_rows": duplicate_rows,
        "unique_values": unique_values,
        "numerical_columns": numerical_columns,
        "categorical_columns": categorical_columns,
        "numerical_statistics": numerical_statistics,
    }