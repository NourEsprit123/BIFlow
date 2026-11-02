def transform(df):
    df = df.copy()
    q1 = df['Unit_Price'].quantile(0.25)
    q3 = df['Unit_Price'].quantile(0.75)
    iqr = q3 - q1
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr
    df['Unit_Price'] = np.where(df['Unit_Price'] < lower_bound, lower_bound, df['Unit_Price'])
    df['Unit_Price'] = np.where(df['Unit_Price'] > upper_bound, upper_bound, df['Unit_Price'])
    return df