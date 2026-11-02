def transform(df):
    import re
    df['Revenue'] = df['Revenue'].str.replace(r'[$,]', '', regex=True)
    df['Revenue'] = df['Revenue'].str.replace(r'k', '000', regex=False)
    df['Revenue'] = df['Revenue'].astype(float)
    return df