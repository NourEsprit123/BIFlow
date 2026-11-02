def transform(df):
    df['numeric_col'] = pd.to_numeric(df['numeric_col'], errors='coerce')
    return df