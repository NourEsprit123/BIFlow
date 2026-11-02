def transform(df):
    df['Revenue'] = df['Revenue'].str.replace('\$|,', '', regex=True)
    df['Revenue'] = df['Revenue'].str.replace('k', '000', case=False)
    df['Revenue'] = pd.to_numeric(df['Revenue'], errors='coerce')
    return df