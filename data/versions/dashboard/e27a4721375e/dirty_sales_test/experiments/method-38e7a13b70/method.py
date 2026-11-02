import pandas as pd
import numpy as np
import re

def transform(df):
    df['Revenue'] = df['Revenue'].astype(str)
    df['Revenue'] = df['Revenue'].str.replace('$', '').str.replace(',', '')
    df['Revenue'] = pd.to_numeric(df['Revenue'], errors='coerce')
    return df