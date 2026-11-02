def transform(df):
    df['PhoneService'] = df['PhoneService'].astype(str).map({'yes': True, 'no': False})
    return df