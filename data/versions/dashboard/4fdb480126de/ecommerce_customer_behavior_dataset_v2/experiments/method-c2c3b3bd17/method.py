def transform(df):
    # Work on a copy to avoid potential SettingWithCopy side‑effects while preserving all other columns
    df = df.copy()
    # Clip Unit_Price to the business‑reasonable range:
    #   lower bound 0  (non‑negative as required by the non_negative check)
    #   upper bound 1126.535 (IQR upper bound identified in the profiling evidence)
    # np.clip works element‑wise and preserves NaN values; there are no NaNs in the source column,
    # but any existing negative values will become 0 and any values above the upper bound will be capped.
    df['Unit_Price'] = df['Unit_Price'].clip(lower=0, upper=1126.535)
    return df