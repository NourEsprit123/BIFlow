def transform(df):
    df['Revenue'] = pd.to_numeric(df['Revenue'].str.replace('k', '000').str.replace('$', '').str.replace(',', '').str.replace('five hundred', '500').str.replace('one thousand', '1000'), errors='coerce')
    return df