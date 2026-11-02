def transform(df):
    df['Dependents'] = df['Dependents'].astype(str).str.lower().map({'yes': True, 'no': False})
    return df