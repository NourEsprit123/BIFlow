def transform(df):
    df['SeniorCitizen'] = df['SeniorCitizen'].astype(bool)
    return df