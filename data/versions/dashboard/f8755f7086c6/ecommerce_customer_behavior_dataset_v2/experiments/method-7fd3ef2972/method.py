def transform(df):
    df = df.copy()
    q1 = df['Delivery_Time_Days'].quantile(0.25)
    q3 = df['Delivery_Time_Days'].quantile(0.75)
    iqr = q3 - q1
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr
    df['Delivery_Time_Days'] = np.where(df['Delivery_Time_Days'] < lower_bound, lower_bound, df['Delivery_Time_Days'])
    df['Delivery_Time_Days'] = np.where(df['Delivery_Time_Days'] > upper_bound, upper_bound, df['Delivery_Time_Days'])
    return df