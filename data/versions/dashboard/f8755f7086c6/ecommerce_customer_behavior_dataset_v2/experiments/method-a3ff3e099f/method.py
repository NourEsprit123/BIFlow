def transform(df):
    df = df.copy()
    q1 = df['Age'].quantile(0.25)
    q3 = df['Age'].quantile(0.75)
    iqr = q3 - q1
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr
    df['Age'] = np.where(df['Age'] < lower_bound, lower_bound, df['Age'])
    df['Age'] = np.where(df['Age'] > upper_bound, upper_bound, df['Age'])
    return df