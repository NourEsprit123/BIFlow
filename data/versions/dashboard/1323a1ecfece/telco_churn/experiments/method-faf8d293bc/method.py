def transform(df):
    df = df.copy()
    df['PhoneService'] = df['PhoneService'].replace({'yes': True, 'no': False}).astype('boolean')
    return df