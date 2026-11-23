"""Create chronological train, evaluation, and test splits for station status data."""

from math import inf
from pathlib import Path

import duckdb
from pandas import DataFrame


def split_station_status_by_time(
    city_dir: str | Path,
) -> tuple[DataFrame, DataFrame, DataFrame]:
    """Return train, evaluation, and test frames ordered by UTC timestamp.

    Use approximately 70%, 15%, and 15% of the dates with recorded updates.
    Each UTC date belongs to one split. Rows with missing or nonfinite
    timestamps are excluded. At least three observed dates are required.
    """
    status_path = str(Path(city_dir) / "station_status.parquet")
    with duckdb.connect() as con:
        days = con.execute(
            """
            SELECT DISTINCT FLOOR(time / 86400) * 86400 AS day_start
            FROM read_parquet(?)
            WHERE isfinite(time)
            ORDER BY day_start
            """,
            [status_path],
        ).fetchall()
        total_days = len(days)
        if total_days < 3:
            raise ValueError(
                "At least three observed UTC dates are required to split the data."
            )

        evaluation_index = min(7 * total_days // 10, total_days - 2)
        test_index = max(17 * total_days // 20, evaluation_index + 1)
        evaluation_start = days[evaluation_index][0]
        test_start = days[test_index][0]

        query = """
            SELECT *
            FROM read_parquet(?)
            WHERE isfinite(time) AND time >= ? AND time < ?
            ORDER BY time, station_id
        """
        intervals = (
            (-inf, evaluation_start),
            (evaluation_start, test_start),
            (test_start, inf),
        )
        train, evaluation, test = (
            con.execute(query, [status_path, start, stop]).df()
            for start, stop in intervals
        )
    return train, evaluation, test
