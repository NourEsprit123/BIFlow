def transform(df):
    df['Dependents'] = df['Dependents'].str.lower().map({'yes': True, 'no': False})
    return df