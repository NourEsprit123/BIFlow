import pandas as pd
import numpy as np

def calculate_metric(df: pd.DataFrame, column: str, operation: str = "sum") -> float:
    """
    Calcule dynamiquement une métrique sur une colonne du DataFrame.
    """
    if column not in df.columns:
        return 0.0
    
    # Conversion propre en numérique pour éviter les erreurs de type
    series = pd.to_numeric(df[column], errors='coerce')
    
    if operation == "sum":
        return float(series.sum())
    elif operation == "mean":
        return float(series.mean())
    elif operation == "median":
        return float(series.median())
    elif operation == "min":
        return float(series.min())
    elif operation == "max":
        return float(series.max())
    elif operation == "count":
        return int(df[column].count())
    elif operation == "unique_count":
        return int(df[column].nunique())
    
    return 0.0

def calculate_rate(df: pd.DataFrame, column: str, target_value) -> float:
    """
    Calcule un taux ou pourcentage de manière dynamique.
    """
    if column not in df.columns or len(df) == 0:
        return 0.0
    matches = (df[column] == target_value).sum()
    rate = (matches / len(df)) * 100
    return round(float(rate), 2)