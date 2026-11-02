def transform(df):
    import re
    df['Revenue'] = df['Revenue'].str.replace(',', '')
    df['Revenue'] = df['Revenue'].str.replace(' ', '')
    df['Revenue'] = df['Revenue'].str.replace('$', '')
    df['Revenue'] = df['Revenue'].str.replace('k', '000').str.replace('m', '000000').str.replace('b', '000000000')
    df['Revenue'] = df['Revenue'].astype(float)
    return df