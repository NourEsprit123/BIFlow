def transform(df):
    values = df['amount'].replace({'five hundred': '500', 'one thousand': '1000', 'three hundred': '300'})
    values = values.str.replace('$', '', regex=False).str.replace(',', '', regex=False)
    values = values.str.replace(r'(\d+\.?\d*)k', lambda x: str(float(x.group(1)) * 1000), regex=True)
    df['amount'] = pd.to_numeric(values, errors='raise')
    return df