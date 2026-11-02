def transform(df):
    def parse(value):
        if pd.isna(value):
            return np.nan
        text = str(value).lower().replace('$', '').replace(',', '')
        if text == 'five hundred':
            return 500.0
        try:
            return float(text[:-1]) * 1000 if text.endswith('k') else float(text)
        except ValueError:
            return np.nan
    df['amount'] = df['amount'].map(parse)
    return df
