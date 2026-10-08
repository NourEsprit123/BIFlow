from analytics.profiler import profile_dataset


DATASET_PATH = "data/raw/telco_churn.csv"


def test_profile_dataset():

    result = profile_dataset(DATASET_PATH)

    assert result["rows"] > 0
    assert result["columns"] > 0

    assert "column_names" in result
    assert "column_types" in result
    assert "missing_values" in result

    assert result["duplicate_rows"] >= 0