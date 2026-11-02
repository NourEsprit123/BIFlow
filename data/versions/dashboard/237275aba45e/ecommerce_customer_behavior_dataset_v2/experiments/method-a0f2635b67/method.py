def transform(df):
    import pandas as pd, numpy as np
    # Work on a copy to preserve original order and unrelated columns
    df = df.copy()
    # Compute IQR bounds for Age
    q1 = df['Age'].quantile(0.25)
    q3 = df['Age'].quantile(0.75)
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    # Identify outliers
    outlier_mask = (df['Age'] < lower) | (df['Age'] > upper)
    # Replace outliers with pandas nullable integer NA, keeping dtype consistent
    df['Age'] = df['Age'].mask(outlier_mask).astype('Int64')
    return df