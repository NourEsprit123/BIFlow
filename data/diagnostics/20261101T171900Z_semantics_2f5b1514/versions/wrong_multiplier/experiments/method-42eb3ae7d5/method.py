def transform(df):
    df['amount'] = pd.to_numeric(df['amount'].str.replace('k', '000'), errors='coerce')
    return df