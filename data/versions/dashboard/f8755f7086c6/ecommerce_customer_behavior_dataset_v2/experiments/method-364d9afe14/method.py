def transform(df):
    df['Pages_Viewed'] = pd.to_numeric(df['Pages_Viewed'], errors='coerce')
    q1 = df['Pages_Viewed'].quantile(0.25)
    q3 = df['Pages_Viewed'].quantile(0.75)
    iqr = q3 - q1
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr
    df['Pages_Viewed'] = np.where(df['Pages_Viewed'] > upper_bound, 17, df['Pages_Viewed'])
    return df