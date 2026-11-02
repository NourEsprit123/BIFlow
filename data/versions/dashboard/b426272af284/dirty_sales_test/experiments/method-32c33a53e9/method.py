def transform(df):
    df['IsActive'] = df['IsActive'].str.lower().map({'yes': True, 'no': False})
    return df