def transform(df):
    df['PhoneService'] = df['PhoneService'].map({'yes': True, 'no': False}).astype('boolean')
    return df