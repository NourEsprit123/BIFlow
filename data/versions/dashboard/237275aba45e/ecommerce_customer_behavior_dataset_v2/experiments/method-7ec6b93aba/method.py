def transform(df):
    df = df.copy()
    q1 = df['Discount_Amount'].quantile(0.25)
    q3 = df['Discount_Amount'].quantile(0.75)
    iqr = q3 - q1
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr
    df['Discount_Amount'] = np.where(df['Discount_Amount'] < lower_bound, lower_bound, df['Discount_Amount'])
    df['Discount_Amount'] = np.where(df['Discount_Amount'] > upper_bound, upper_bound, df['Discount_Amount'])
    return df