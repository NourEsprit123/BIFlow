def transform(df):
    df = df.copy()
    df['Pages_Viewed'] = pd.to_numeric(df['Pages_Viewed'], errors='coerce')
    df['Pages_Viewed'] = df['Pages_Viewed'].clip(upper=17)
    return df