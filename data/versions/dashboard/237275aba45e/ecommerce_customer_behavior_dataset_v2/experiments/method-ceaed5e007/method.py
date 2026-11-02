def transform(df):
    import numpy as np
    # Work on a copy to guarantee original DataFrame stays untouched
    df = df.copy()
    # Compute IQR bounds for Unit_Price
    q1 = df['Unit_Price'].quantile(0.25)
    q3 = df['Unit_Price'].quantile(0.75)
    iqr = q3 - q1
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr
    # Cap values outside the bounds while leaving other columns unchanged
    df.loc[df['Unit_Price'] < lower_bound, 'Unit_Price'] = lower_bound
    df.loc[df['Unit_Price'] > upper_bound, 'Unit_Price'] = upper_bound
    return df