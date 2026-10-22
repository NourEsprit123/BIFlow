import pandas as pd
import numpy as np
from analytics.cleaning import clean_dirty_numeric_series, impute_missing_values


def test_clean_dirty_numeric_series():
    s = pd.Series(["$12.50", "34.0", " 100 ", "N/A", "2.5k"])
    cleaned = clean_dirty_numeric_series(s)
    assert cleaned.iloc[0] == 12.50
    assert cleaned.iloc[1] == 34.0
    assert cleaned.iloc[2] == 100.0


def test_impute_missing_values_median():
    df = pd.DataFrame({"val": [10.0, np.nan, 30.0, 40.0]})
    res = impute_missing_values(df, {"val": {"strategy": "median"}})
    assert res["val"].isnull().sum() == 0
    assert res["val"].iloc[1] == 30.0
