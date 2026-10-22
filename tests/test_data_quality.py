import pandas as pd

from analytics.data_quality import detect_cross_column_issues


def test_detect_cross_column_issues_finds_reversed_dates_and_bounds():
    df = pd.DataFrame(
        {
            "start_date": ["2025-02-01", "2025-01-01", "invalid"],
            "end_date": ["2025-01-01", "2025-02-01", "2025-03-01"],
            "amount_min": [10, 1, None],
            "amount_max": [5, 2, 3],
        },
        index=[10, 11, 12],
    )

    issues = detect_cross_column_issues(df)

    assert [(issue["type"], issue["violation_count"]) for issue in issues] == [
        ("invalid_numeric_bounds", 1),
        ("invalid_date_order", 1),
    ]
    assert issues[0]["examples"] == [10]
    assert issues[1]["examples"] == [10]


def test_detect_cross_column_issues_returns_empty_for_empty_or_valid_data():
    assert detect_cross_column_issues(pd.DataFrame()) == []
    assert detect_cross_column_issues(
        pd.DataFrame(
            {
                "begin": ["2025-01-01"],
                "finish": ["2025-01-02"],
                "score_lower": [1],
                "score_upper": [2],
            }
        )
    ) == []
