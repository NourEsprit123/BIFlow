import pandas as pd
from pandas.testing import assert_frame_equal

from dataCleaningTools.cleaning import clean_numeric_string, convert_data_types


def test_convert_data_types_parses_normalized_boolean_strings():
    df = pd.DataFrame({"flag": ["true", "false", " Yes ", "NO", "1", "0", None]})

    result = convert_data_types(df, "flag", "boolean")

    assert result.success
    assert result.df is not None
    assert str(result.df["flag"].dtype) == "boolean"
    assert result.df["flag"].tolist() == [
        True, False, True, False, True, False, pd.NA
    ]


def test_convert_data_types_boolean_coerces_unrecognized_values():
    df = pd.DataFrame({"flag": ["yes", "unknown"]})

    result = convert_data_types(df, "flag", "boolean", errors="coerce")

    assert result.success
    assert result.df is not None
    assert result.df["flag"].tolist() == [True, pd.NA]
    assert result.affected_rows == 1


def test_convert_data_types_boolean_error_modes():
    df = pd.DataFrame({"flag": ["yes", "unknown"]})

    raised = convert_data_types(df, "flag", "boolean", errors="raise")
    ignored = convert_data_types(df, "flag", "boolean", errors="ignore")

    assert not raised.success
    assert raised.error is not None
    assert "unknown" in raised.error
    assert ignored.success
    assert ignored.df is not None
    assert_frame_equal(ignored.df, df)


def test_convert_data_types_ignores_invalid_numeric_and_datetime_columns():
    numeric_df = pd.DataFrame({"value": ["10", "not-a-number"]})
    datetime_df = pd.DataFrame({"value": ["2025-01-01", "not-a-date"]})

    numeric_result = convert_data_types(
        numeric_df, "value", "numeric", errors="ignore"
    )
    datetime_result = convert_data_types(
        datetime_df, "value", "datetime", errors="ignore"
    )

    assert numeric_result.success
    assert numeric_result.df is not None
    assert_frame_equal(numeric_result.df, numeric_df)
    assert datetime_result.success
    assert datetime_result.df is not None
    assert_frame_equal(datetime_result.df, datetime_df)


def test_clean_numeric_string_coerces_unparseable_values():
    df = pd.DataFrame({"amount": ["$1,200.50", "1.5k", "banana"]})

    result = clean_numeric_string(df, "amount")

    assert result.success
    assert result.df is not None
    assert result.df["amount"].iloc[:2].tolist() == [1200.5, 1500.0]
    assert pd.isna(result.df["amount"].iloc[2])


def test_clean_numeric_string_raise_and_ignore_modes():
    df = pd.DataFrame({"amount": ["1.5k", "banana"]})

    raised = clean_numeric_string(df, "amount", errors="raise")
    ignored = clean_numeric_string(df, "amount", errors="ignore")

    assert not raised.success
    assert raised.error is not None
    assert "banana" in raised.error
    assert ignored.success
    assert ignored.df is not None
    assert_frame_equal(ignored.df, df)