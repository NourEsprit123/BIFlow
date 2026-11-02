import pandas as pd
import re

def transform(df):
    df['Revenue'] = df['Revenue'].str.replace('$', '', regex=False).str.replace(',', '', regex=False)
    df['Revenue'] = df['Revenue'].str.replace('k', '000', regex=False)
    df['Revenue'] = df['Revenue'].str.replace('one thousand', '1000', regex=False)
    df['Revenue'] = df['Revenue'].str.replace('five hundred', '500', regex=False)
    df['Revenue'] = pd.to_numeric(df['Revenue'], errors='coerce')
    return df