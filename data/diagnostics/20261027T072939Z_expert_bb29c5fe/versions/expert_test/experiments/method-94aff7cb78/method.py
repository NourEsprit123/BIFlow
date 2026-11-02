def transform(df):
    values = df['amount'].replace({'five hundred': '500', 'one thousand': '1000'})
    values = values.str.replace('$', '', regex=False).str.replace(',', '', regex=False).str.replace('k', '000', regex=False)
    df['amount'] = pd.to_numeric(values, errors='raise')
    return df
