def transform(df):
    df['IsActive'] = df['IsActive'].map({'yes': True, 'no': False})
    return df