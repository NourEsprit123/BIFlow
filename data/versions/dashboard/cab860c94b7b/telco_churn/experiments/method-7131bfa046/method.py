def transform(df):
    df['PhoneService'] = df['PhoneService'].map({'Yes': True, 'No': False})
    return df