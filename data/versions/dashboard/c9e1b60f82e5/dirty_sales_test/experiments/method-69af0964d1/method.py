def transform(df):
    import re
    df['Revenue'] = df['Revenue'].str.replace(',', '')
    df['Revenue'] = df['Revenue'].str.replace('$', '')
    df['Revenue'] = df['Revenue'].str.replace('k', '000')
    df['Revenue'] = pd.to_numeric(df['Revenue'], errors='coerce')
    return df