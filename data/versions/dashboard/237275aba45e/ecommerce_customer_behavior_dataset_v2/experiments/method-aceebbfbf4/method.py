def transform(df):
    df = df.copy()
    q1 = df['Session_Duration_Minutes'].quantile(0.25)
    q3 = df['Session_Duration_Minutes'].quantile(0.75)
    iqr = q3 - q1
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr
    df['Session_Duration_Minutes'] = np.where(df['Session_Duration_Minutes'] > upper_bound, np.nan, df['Session_Duration_Minutes'])
    df['Session_Duration_Minutes'] = np.where(df['Session_Duration_Minutes'] < lower_bound, np.nan, df['Session_Duration_Minutes'])
    return df