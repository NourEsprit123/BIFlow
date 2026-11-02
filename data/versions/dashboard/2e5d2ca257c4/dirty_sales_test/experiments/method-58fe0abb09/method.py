import pandas as pd
import numpy as np
import re

def transform(df):
    df['Revenue'] = df['Revenue'].astype(str)
    df['Revenue'] = df['Revenue'].str.replace('$', '', regex=False)
    df['Revenue'] = df['Revenue'].str.replace(',', '', regex=False)
    df['Revenue'] = df['Revenue'].str.replace('k', '000', regex=False)
    df['Revenue'] = df['Revenue'].str.replace('million', '000000', regex=False)
    df['Revenue'] = df['Revenue'].str.replace('thousand', '000', regex=False)
    df['Revenue'] = df['Revenue'].str.replace(' ', '', regex=False)
    df['Revenue'] = df['Revenue'].str.replace('ERROR', '', regex=False)
    df['Revenue'] = df['Revenue'].str.replace('banana', '', regex=False)
    df['Revenue'] = df['Revenue'].str.replace('ERROR_404', '', regex=False)
    df['Revenue'] = pd.to_numeric(df['Revenue'], errors='coerce')
    return df