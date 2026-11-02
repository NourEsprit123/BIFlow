import pandas as pd

def transform(df):
    df['MonthlyCost'] = pd.to_numeric(df['MonthlyCost'].str.replace('\$', '', regex=False).str.replace(',', '', regex=False), errors='coerce')
    return df