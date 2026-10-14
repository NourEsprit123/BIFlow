import re
from typing import Any, Dict

import pandas as pd
from sqlalchemy import create_engine, text


def dataset_table_name(file_path: str) -> str:
    """Create a stable PostgreSQL table name from a dataset filename."""
    base_name = file_path.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    table_name = re.sub(r"[^a-zA-Z0-9_]+", "_", base_name).strip("_").lower()
    if not table_name:
        raise ValueError("The dataset filename does not produce a valid PostgreSQL table name.")
    if table_name[0].isdigit():
        table_name = f"dataset_{table_name}"
    return table_name


def load_dataframe_to_postgres(
    dataframe: pd.DataFrame,
    database_url: str,
    table_name: str,
    schema: str = "analytics",
) -> Dict[str, Any]:
    """Replace a dataset table in PostgreSQL with the latest cleaned dataframe."""
    for value, label in ((schema, "schema"), (table_name, "table name")):
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", value):
            raise ValueError(f"Invalid PostgreSQL {label}: {value!r}")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
            dataframe.to_sql(
                name=table_name,
                con=connection,
                schema=schema,
                if_exists="replace",
                index=False,
                method="multi",
                chunksize=1000,
            )
    finally:
        engine.dispose()

    return {
        "status": "loaded",
        "schema": schema,
        "table": table_name,
        "rows_loaded": len(dataframe),
    }