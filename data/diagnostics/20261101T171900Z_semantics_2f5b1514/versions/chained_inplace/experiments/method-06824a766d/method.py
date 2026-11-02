def transform(df):
    df['amount'].fillna(df['amount'].median(), inplace=True)
    return df