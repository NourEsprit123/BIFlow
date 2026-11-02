def transform(df):
    df['numeric_column'] = pd.to_numeric(df['numeric_column'], errors='coerce')
    df['numeric_column'] = df['numeric_column'].fillna(df['numeric_column'].mean())
    return df