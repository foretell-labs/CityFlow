"""Inspect station status updates."""

from pathlib import Path

import duckdb


def station_status_mismatch_ratio(city_dir: str | Path) -> float | None:
    """Return the fraction of updates with a nonzero bike count difference.

    Divide by all updates, including rows with missing counts. A row with
    a missing count cannot be marked as a mismatch. Return None for an
    empty station_status.parquet file.
    """
    status_path = Path(city_dir) / "station_status.parquet"
    with duckdb.connect() as con:
        return con.execute(
            """
            SELECT COUNT(*) FILTER (
                       WHERE bikes - booked_bikes - bikes_available_to_rent <> 0
                   ) / NULLIF(COUNT(*), 0)
            FROM read_parquet(?)
            """,
            [str(status_path)],
        ).fetchall()[0][0]
