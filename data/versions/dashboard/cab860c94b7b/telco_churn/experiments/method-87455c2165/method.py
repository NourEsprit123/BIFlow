def transform(df):
    median_charge = df['TotalCharges'].median()
    df['TotalCharges'] = df['TotalCharges'].fillna(median_charge)
    return df