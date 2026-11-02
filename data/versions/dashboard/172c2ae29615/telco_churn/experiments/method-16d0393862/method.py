def transform(df):
    df['Partner'] = df['Partner'].str.lower().map({'yes': True, 'no': False})
    return df