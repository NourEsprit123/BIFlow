def transform(df):
    import re
    df['Revenue'] = df['Revenue'].str.replace(',', '')
    df['Revenue'] = df['Revenue'].str.replace('$', '')
    df['Revenue'] = df['Revenue'].str.replace('k', '000').str.replace('m', '000000').str.strip()
    df['Revenue'] = df['Revenue'].astype(float)
    return df