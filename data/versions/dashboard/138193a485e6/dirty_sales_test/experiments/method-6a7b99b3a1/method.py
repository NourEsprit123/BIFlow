def transform(df):
    def parse_revenue(s):
        if pd.isna(s):
            return s
        s = str(s).replace('$', '').replace(',', '')
        if 'k' in s:
            return float(s.replace('k', '').strip()) * 1000
        return float(s)
    df['Revenue'] = df['Revenue'].apply(parse_revenue)
    return df