def transform(df):
    values = df['amount']
    values = values.str.replace('$', '', regex=False).str.replace(',', '', regex=False).str.replace('k', '000', regex=False)
    df['amount'] = pd.to_numeric(values, errors='raise')
    return df
