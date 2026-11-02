def transform(df):
    df['signup_date'] = pd.to_datetime(df['signup_date'], errors='coerce')
    df['signup_date'] = df['signup_date'].fillna('Unknown')
    return df