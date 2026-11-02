def transform(df):
    import re
    df['Revenue'] = df['Revenue'].str.replace(',', '')
    df['Revenue'] = df['Revenue'].str.replace('$', '')
    df['Revenue'] = df['Revenue'].str.replace('k', '000')
    df['Revenue'] = df['Revenue'].str.replace(' ', '')
    df['Revenue'] = df['Revenue'].astype(float)
    return df