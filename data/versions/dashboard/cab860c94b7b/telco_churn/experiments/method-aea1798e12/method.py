def transform(df):
    df['TotalCharges'] = pd.to_numeric(df['TotalCharges'], errors='coerce')
    return df