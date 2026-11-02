def transform(df):
    def clean_revenue(value):
        value = value.replace(',', '')
        if value.startswith('$'):
            value = value[1:]
        if value.endswith('k'):
            value = value[:-1] * 1000
        if value.endswith('m'):
            value = value[:-1] * 1000000
        return float(value)
    df['Revenue'] = df['Revenue'].apply(clean_revenue)
    return df