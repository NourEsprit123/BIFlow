def transform(df):
    import re
    df['Revenue'] = df['Revenue'].str.replace(',', '').str.replace('$', '').str.replace('k', '000').str.replace('m', '000000').str.strip().replace('banana', np.nan).replace('ERROR_404', np.nan)
    df['Revenue'] = pd.to_numeric(df['Revenue'], errors='coerce')
    return df