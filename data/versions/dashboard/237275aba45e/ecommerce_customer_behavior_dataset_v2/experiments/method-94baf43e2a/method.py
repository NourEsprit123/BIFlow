def transform(df):
    df = df.copy()
    q1 = df['Total_Amount'].quantile(0.25)
    q3 = df['Total_Amount'].quantile(0.75)
    iqr = q3 - q1
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr
    df['Total_Amount'] = np.where(df['Total_Amount'] > upper_bound, upper_bound, df['Total_Amount'])
    df['Total_Amount'] = np.where(df['Total_Amount'] < lower_bound, lower_bound, df['Total_Amount'])
    return df