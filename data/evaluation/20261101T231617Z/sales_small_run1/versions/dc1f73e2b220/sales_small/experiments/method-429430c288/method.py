def transform(df):
    df['region'] = df['region'].str.strip()
    return df