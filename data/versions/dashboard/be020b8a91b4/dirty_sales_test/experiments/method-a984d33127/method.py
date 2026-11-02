def transform(df):
    df['Revenue'] = df['Revenue'].str.replace('$', '').str.replace(',', '').str.replace('k', '000').astype(float)
    return df