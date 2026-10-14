import pandas as pd
import pytest

from analytics import etl
from analytics.etl import dataset_table_name, load_dataframe_to_postgres


def test_dataset_table_name_is_safe_and_stable():
    assert dataset_table_name(r"D:\BIFlow\data\raw\Dirty Sales-test.csv") == "dirty_sales_test"
    assert dataset_table_name("123 data.csv") == "dataset_123_data"


def test_load_dataframe_replaces_table_contents(monkeypatch):
    calls = {}

    class FakeConnection:
        def execute(self, statement):
            calls["schema_statement"] = str(statement)

    class Transaction:
        def __enter__(self):
            return FakeConnection()

        def __exit__(self, exc_type, exc_value, traceback):
            return False

    class FakeEngine:
        def begin(self):
            return Transaction()

        def dispose(self):
            calls["disposed"] = True

    def fake_create_engine(url, **kwargs):
        calls["url"] = url
        return FakeEngine()

    def fake_to_sql(self, **kwargs):
        calls["to_sql"] = kwargs

    monkeypatch.setattr(etl, "create_engine", fake_create_engine)
    monkeypatch.setattr(pd.DataFrame, "to_sql", fake_to_sql)

    result = load_dataframe_to_postgres(
        pd.DataFrame({"Revenue": [100.0, 200.0]}),
        "postgresql+psycopg://user:password@localhost/biflow",
        "sales",
    )

    assert result == {
        "status": "loaded",
        "schema": "analytics",
        "table": "sales",
        "rows_loaded": 2,
    }
    assert calls["to_sql"]["if_exists"] == "replace"
    assert calls["to_sql"]["schema"] == "analytics"
    assert "CREATE SCHEMA IF NOT EXISTS" in calls["schema_statement"]
    assert calls["disposed"]


@pytest.mark.parametrize("schema,table", [
    ("analytics; DROP SCHEMA public", "sales"),
    ("analytics", "sales-data"),
])
def test_load_dataframe_rejects_invalid_identifiers(schema, table):
    with pytest.raises(ValueError, match="Invalid PostgreSQL"):
        load_dataframe_to_postgres(
            pd.DataFrame({"Revenue": [1]}),
            "postgresql+psycopg://user:password@localhost/biflow",
            table,
            schema=schema,
        )
