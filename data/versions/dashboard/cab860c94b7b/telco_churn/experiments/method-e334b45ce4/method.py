def transform(df):
    df['Partner'] = df['Partner'].map({'Yes': True, 'No': False})
    return df