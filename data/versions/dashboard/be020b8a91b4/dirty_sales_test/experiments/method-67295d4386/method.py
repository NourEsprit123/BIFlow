def transform(df):
    df['Revenue'] = pd.to_numeric(df['Revenue'].str.replace('k', '000').str.replace('$', '').str.replace(',', ''), errors='coerce')
    return df