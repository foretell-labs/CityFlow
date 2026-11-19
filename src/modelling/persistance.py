"""Predict a station's shortage risk by carrying forward its latest status."""

from math import isfinite
from pathlib import Path

import duckdb


def predict_persistence(
    city_dir: str | Path, station_id: int, time: float
) -> int | None:
    """Predict shortage from the most recent update at or before the given time.

    Time is a Unix timestamp in seconds. Return 1 for at most two rentable
    bikes, 0 for more than two, or None if the latest count is unavailable.
    """
    if not isfinite(time):
        raise ValueError("time must be a finite Unix timestamp in seconds")

    status_path = Path(city_dir) / "station_status.parquet"
    with duckdb.connect() as con:
        rows = con.execute(
            """
            SELECT CAST(bikes_available_to_rent <= 2 AS INTEGER) AS at_risk
            FROM read_parquet(?)
            WHERE station_id = ? AND time <= ?
            ORDER BY time DESC
            LIMIT 1
            """,
            [str(status_path), station_id, time],
        ).fetchall()
    return rows[0][0] if rows else None
