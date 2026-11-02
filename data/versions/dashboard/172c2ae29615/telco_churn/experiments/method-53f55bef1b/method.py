def transform(df):
    df['Dependents'] = df['Dependents'].map({'yes': True, 'no': False}).astype('boolean')
    return df