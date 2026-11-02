def transform(df):
    df = df.copy()
    df['Discount_Amount'] = pd.to_numeric(df['Discount_Amount'], errors='coerce')
    df['Discount_Amount'] = df['Discount_Amount'].clip(upper=81.775)
    return df