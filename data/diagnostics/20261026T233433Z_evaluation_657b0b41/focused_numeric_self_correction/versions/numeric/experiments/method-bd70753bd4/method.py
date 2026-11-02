def transform(df):
    df['value'] = df['value'].str.replace('five hundred', '500', regex=False)
    df['value'] = df['value'].str.replace('one thousand', '1000', regex=False)
    df['value'] = df['value'].str.replace('k', '000', regex=False)
    df['value'] = df['value'].str.replace('$', '', regex=False)
    df['value'] = df['value'].str.replace(',', '', regex=False)
    df['value'] = df['value'].astype(float)
    return df