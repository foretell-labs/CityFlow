"""Function that temporarily fixes pyrefly issues.

The issue regards the possibility of fetch_one to return None.
"""

import duckdb


def fetch_one(
    con: duckdb.DuckDBPyConnection, query: str, parameters: object = None
) -> tuple:
    row = con.execute(query, parameters=parameters).fetchone()
    if row is None:
        raise ValueError(f"Query returned no rows:\n{query}")
    return row
