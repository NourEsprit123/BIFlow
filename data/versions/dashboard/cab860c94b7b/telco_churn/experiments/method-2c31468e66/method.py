def transform(df):
    df['PaperlessBilling'] = df['PaperlessBilling'].map({'Yes': True, 'No': False})
    return df