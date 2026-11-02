import pandas as pd
import numpy as np
import re

def transform(df):
    df['Revenue'] = df['Revenue'].astype(str)
    df['Revenue'] = df['Revenue'].str.replace('$', '', regex=True)
    df['Revenue'] = df['Revenue'].str.replace(',', '', regex=True)
    df['Revenue'] = df['Revenue'].str.replace('k', '000', regex=True)
    df['Revenue'] = df['Revenue'].str.replace('m', '000000', regex=True)
    df['Revenue'] = df['Revenue'].str.replace('b', '000000000', regex=True)
    df['Revenue'] = df['Revenue'].str.replace('quarter', '250000', regex=True)
    df['Revenue'] = df['Revenue'].str.replace('five hundred', '500', regex=True)
    df['Revenue'] = df['Revenue'].str.replace('one thousand', '1000', regex=True)
    df['Revenue'] = pd.to_numeric(df['Revenue'], errors='coerce')
    return df