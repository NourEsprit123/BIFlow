import pandas as pd
import re

def transform(df):
    def parse_monthly_cost(value):
        if pd.isna(value):
            return value
        # Remove currency symbol and commas
        cleaned_value = re.sub(r'[,$]', '', str(value))
        # Convert to float
        try:
            return float(cleaned_value)
        except ValueError:
            return value
    df['MonthlyCost'] = df['MonthlyCost'].apply(parse_monthly_cost)
    return df