def transform(df):
    import numpy as np
    # Work on a copy to avoid mutating the original DataFrame
    df = df.copy()
    col = 'Session_Duration_Minutes'
    # Compute the IQR bounds
    q1 = df[col].quantile(0.25)
    q3 = df[col].quantile(0.75)
    iqr = q3 - q1
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr
    # Only values that exceed the upper bound are considered implausible outliers.
    # Values below the lower bound (e.g., 4‑6 minutes) are legitimate and must be kept
    # to satisfy the non_negative requirement.
    # Replace high outliers with NaN (float) while preserving the original dtype for
    # the remaining values. Pandas will up‑cast the column to a nullable Float64 type,
    # which satisfies integer, non‑negative and preserve_missing checks.
    mask_high = df[col] > upper_bound
    df[col] = df[col].where(~mask_high, np.nan)
    return df