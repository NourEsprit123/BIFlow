def transform(df):
    df['Dependents'] = df['Dependents'].map({'No': False, 'Yes': True})
    return df