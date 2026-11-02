def transform(df):
    df['amount'] = pd.to_numeric(df['amount'].str.replace('\\$', '', regex=False), errors='coerce')
    return df