def transform(df):
    df['PhoneService'] = df['PhoneService'].astype(str).map({'yes': True, 'no': False}).astype('boolean')
    return df