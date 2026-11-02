import pandas as pd

def transform(df):
    df['SignupDate'] = pd.to_datetime(df['SignupDate'], errors='coerce')
    df['SignupDate'] = df['SignupDate'].fillna('Unknown')
    return df