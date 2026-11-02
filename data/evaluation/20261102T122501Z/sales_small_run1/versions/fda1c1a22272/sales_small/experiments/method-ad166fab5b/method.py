def transform(df):
    df['signup_date'] = pd.to_datetime(df['signup_date'], errors='coerce')
    return df