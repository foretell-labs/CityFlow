"""Analyze the timing of recorded station status updates."""

from pathlib import Path

import duckdb
from matplotlib import pyplot as plt
from matplotlib.axes import Axes
from matplotlib.dates import AutoDateLocator, ConciseDateFormatter, date2num
from pandas import DataFrame


def hourly_station_status_changes(city_dir: str | Path, deltaT: int = 1) -> DataFrame:
    """Count recorded updates in deltaT-hour UTC intervals per city station.

    Each status row for a known station counts, including its first observation.
    The denominator is the number of unique station IDs in stations.parquet.
    Intervals are aligned to midnight UTC on 1970-01-01 and include
    empty intervals between the first and last update. The hour_utc column
    contains the start of each interval.
    """
    if isinstance(deltaT, bool) or not isinstance(deltaT, int) or deltaT < 1:
        raise ValueError("deltaT must be a positive integer number of hours")

    city_dir = Path(city_dir)
    with duckdb.connect() as con:
        return con.execute(
            """
            WITH interval_width AS (
                SELECT ? * INTERVAL 1 HOUR AS width
            ),
            stations AS (
                SELECT DISTINCT id FROM read_parquet(?) WHERE id IS NOT NULL
            ),
            hourly AS (
                SELECT time_bucket(
                    (SELECT width FROM interval_width),
                    timezone('UTC', to_timestamp(t.time)),
                    TIMESTAMP '1970-01-01 00:00:00'
                ) AS hour_utc,
                       COUNT(*) AS status_changes
                FROM read_parquet(?) t
                JOIN stations s ON t.station_id = s.id
                WHERE isfinite(t.time)
                GROUP BY hour_utc
            ),
            calendar AS (
                SELECT UNNEST(generate_series(
                    MIN(hour_utc), MAX(hour_utc), (SELECT width FROM interval_width)
                )) AS hour_utc
                FROM hourly
            )
            SELECT c.hour_utc,
                   COALESCE(h.status_changes, 0) AS status_changes,
                   COALESCE(h.status_changes, 0) /
                       (SELECT COUNT(*) FROM stations) AS changes_per_station
            FROM calendar c
            LEFT JOIN hourly h USING (hour_utc)
            ORDER BY c.hour_utc
            """,
            [
                deltaT,
                str(city_dir / "stations.parquet"),
                str(city_dir / "station_status.parquet"),
            ],
        ).df()


def plot_hourly_station_status_changes(city_dir: str | Path, deltaT: int = 1) -> Axes:
    """Plot the number of recorded status updates per station in each interval."""
    city_dir = Path(city_dir)
    hourly = hourly_station_status_changes(city_dir, deltaT=deltaT)

    _, ax = plt.subplots(figsize=(11, 4), layout="constrained")
    ax.plot(
        date2num(hourly["hour_utc"].to_numpy()),
        hourly["changes_per_station"].to_numpy(),
        linewidth=0.8,
    )
    locator = AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(ConciseDateFormatter(locator))
    ax.set(
        title=f"{city_dir.name.title()} station status updates",
        xlabel=f"Start of {deltaT}-hour interval (UTC)",
        ylabel="Recorded updates per station",
        ylim=(0, None),
    )
    ax.grid(axis="y", alpha=0.25)
    return ax
