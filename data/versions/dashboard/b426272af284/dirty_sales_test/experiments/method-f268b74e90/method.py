def transform(df):
    df['Revenue'] = pd.to_numeric(df['Revenue'], errors='coerce')
    median_revenue = df['Revenue'].median()
    df['Revenue'].fillna(median_revenue, inplace=True)
    return df