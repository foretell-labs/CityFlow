"""Inspect station status updates."""

from pathlib import Path

import duckdb
from pandas import DataFrame

SMALL_STATION_MAX_AVG_BIKES = 6


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


def station_rack_summary(city_dir: str | Path) -> DataFrame:
    """Return rack consistency metrics for each station in the city's metadata.

    For positive bike_racks, divide mismatches by all updates for the station.
    Report the mean and population standard deviation of rentable bike counts.
    The dimension is small at a mean of nine or fewer and big above nine.
    When the mean is unavailable, dimension is null.
    """
    city_dir = Path(city_dir)
    with duckdb.connect() as con:
        return con.execute(
            """
            WITH stations AS (
                SELECT id AS station_id,
                       ANY_VALUE(name) AS station_name,
                       CASE WHEN MIN(bike_racks) = MAX(bike_racks)
                            THEN MIN(bike_racks) END AS bike_racks
                FROM read_parquet(?)
                WHERE id IS NOT NULL
                GROUP BY id
            )
            SELECT s.station_id,
                   s.station_name,
                   s.bike_racks,
                   CASE
                       WHEN s.bike_racks > 0 THEN COUNT(*) FILTER (
                           WHERE s.bike_racks - t.bikes - t.free_racks <> 0
                       ) / NULLIF(COUNT(t.station_id), 0)
                       WHEN s.bike_racks = 0 THEN 0.0
                   END AS rack_mismatch_ratio,
                   CASE
                       WHEN s.bike_racks = 0 THEN AVG(t.bikes_available_to_rent)
                       WHEN s.bike_racks > 0 THEN AVG(t.bikes_available_to_rent)
                   END AS mean_available_bikes,
                   CASE
                       WHEN s.bike_racks = 0 THEN STDDEV_POP(t.bikes_available_to_rent)
                       WHEN s.bike_racks > 0 THEN STDDEV_POP(t.bikes_available_to_rent)
                   END AS std_available_bikes,
                   CASE
                       WHEN mean_available_bikes IS NULL THEN NULL
                        WHEN mean_available_bikes <= ? THEN 'small'
                        ELSE 'big'
                   END AS dimension
            FROM stations AS s
            LEFT JOIN read_parquet(?) AS t ON t.station_id = s.station_id
            GROUP BY s.station_id, s.station_name, s.bike_racks
            ORDER BY s.station_id
            """,
            [
                str(city_dir / "stations.parquet"),
                SMALL_STATION_MAX_AVG_BIKES,
                str(city_dir / "station_status.parquet"),
            ],
        ).df()
