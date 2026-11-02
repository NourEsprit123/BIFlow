import pandas as pd

def transform(df):
    df['SignupDate'] = pd.to_datetime(df['SignupDate'], errors='coerce')
    return df