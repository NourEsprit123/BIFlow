def transform(df):
    df['Partner'] = df['Partner'].map({'yes': True, 'no': False})
    return df