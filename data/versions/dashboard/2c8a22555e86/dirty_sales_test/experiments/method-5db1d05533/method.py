import pandas as pd
import re

def transform(df):
    def clean_monthly_cost(value):
        if pd.isna(value):
            return value
        # Remove currency symbol and commas
        cleaned = re.sub(r'[,$]', '', str(value))
        # Convert to float
        try:
            return float(cleaned)
        except ValueError:
            return value
    df['MonthlyCost'] = df['MonthlyCost'].apply(clean_monthly_cost)
    return df