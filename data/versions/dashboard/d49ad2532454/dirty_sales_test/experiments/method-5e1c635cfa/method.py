def transform(df):
    def clean_revenue(value):
        value = value.strip()
        if value.startswith('$'):
            value = value[1:]
        if 'k' in value:
            value = value.replace('k', '000')
        if ',' in value:
            value = value.replace(',', '')
        if '.' in value:
            return float(value)
        else:
            return int(value)
    df['Revenue'] = df['Revenue'].apply(clean_revenue)
    return df