def transform(df):
    def parse_revenue(s):
        if pd.isna(s):
            return s
        s = str(s).replace('$', '').replace(',', '').strip()
        if 'k' in s:
            s = s.replace('k', '').strip()
        try:
            return float(s)
        except ValueError:
            return s
    df['Revenue'] = df['Revenue'].apply(parse_revenue)
    return df