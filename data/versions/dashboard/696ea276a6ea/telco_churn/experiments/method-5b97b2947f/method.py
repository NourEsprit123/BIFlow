def transform(df):
    df['column'] = df['column'].replace({'Yes': True, 'No': False}).astype(bool)
    return df