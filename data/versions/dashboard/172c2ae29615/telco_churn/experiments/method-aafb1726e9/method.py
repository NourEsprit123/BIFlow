def transform(df):
    df['Dependents'] = df['Dependents'].replace({'yes': True, 'no': False}).astype('boolean')
    return df