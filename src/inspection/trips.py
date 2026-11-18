"""Inspect city trip records."""

from datetime import date
from pathlib import Path

import duckdb


def count_trips_missing_station_ids(city_dir: str | Path) -> int:
    """Count trip rows missing a start station, an end station, or both.

    Reads trips.parquet from the given city directory.
    """
    city_dir = Path(city_dir)
    with duckdb.connect() as con:
        return con.execute(
            """
            SELECT COUNT(*)
            FROM read_parquet(?)
            WHERE station_id_start IS NULL OR station_id_end IS NULL
            """,
            [str(city_dir / "trips.parquet")],
        ).fetchone()[0]


def days_with_missing_station_ids(city_dir: str | Path, n: int = 1, *, timezone: str = "UTC") -> tuple[list[date], float | None]:
    """Return the trip start dates with at least n incomplete trips and their ratio.

    A trip is incomplete when its start or end station ID is missing.
    The denominator counts both the earliest and latest trip start dates.
    Return None for the ratio when there are no usable trip start dates.
    """
    if n < 1:
        raise ValueError("n must be at least 1")

    trips_path = Path(city_dir) / "trips.parquet"
    with duckdb.connect() as con:
        dates, elapsed_days = con.execute(
            """
            WITH daily AS (
                SELECT CAST(timezone(?, to_timestamp(time_start)) AS DATE) AS trip_date,
                       COUNT(*) FILTER (
                           WHERE station_id_start IS NULL OR station_id_end IS NULL
                       ) AS missing_trips
                FROM read_parquet(?)
                WHERE isfinite(time_start)
                GROUP BY trip_date
            )
            SELECT LIST(trip_date ORDER BY trip_date) FILTER (WHERE missing_trips >= ?),
                   MAX(trip_date) - MIN(trip_date) + 1
            FROM daily
            """,
            [timezone, str(trips_path), n],
        ).fetchone()

    dates = dates or []
    ratio = len(dates) / elapsed_days if elapsed_days is not None else None
    return dates, ratio
