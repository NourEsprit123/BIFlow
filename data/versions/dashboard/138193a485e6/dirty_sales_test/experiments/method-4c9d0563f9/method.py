def transform(df):
    def parse_revenue(s):
        if pd.isna(s):
            return s
        s = str(s).replace('$', '').replace(',', '')
        if 'k' in s:
            s = s.replace('k', '').strip()
        if re.fullmatch(r'\d+\.?\d*', s):
            return float(s)
        return pd.NA
    df['Revenue'] = df['Revenue'].apply(parse_revenue)
    return df