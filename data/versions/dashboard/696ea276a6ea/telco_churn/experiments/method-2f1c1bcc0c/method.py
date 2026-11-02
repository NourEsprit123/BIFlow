def transform(df):
    df['Dependents'] = df['Dependents'].map({'no': False, 'yes': True})
    return df