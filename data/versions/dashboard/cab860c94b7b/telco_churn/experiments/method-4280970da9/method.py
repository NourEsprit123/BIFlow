def transform(df):
    df['Churn'] = df['Churn'].map({'Yes': True, 'No': False}).astype('boolean')
    return df