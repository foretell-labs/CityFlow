"""Inspect city trip records."""

from collections.abc import Sequence
from datetime import date, timedelta
from math import nan
from pathlib import Path

import duckdb
from matplotlib import pyplot as plt
from matplotlib.axes import Axes
from matplotlib.dates import AutoDateLocator, ConciseDateFormatter, date2num
from matplotlib.ticker import PercentFormatter


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
        ).fetchall()[0][0]


def _daily_trip_counts(
    con: duckdb.DuckDBPyConnection, trips_path: Path, timezone: str
) -> list[tuple[date, int, int]]:
    """Return each observed trip start date, trip count, and missing-ID count."""
    return con.execute(
        """
        SELECT CAST(timezone(?, to_timestamp(time_start)) AS DATE) AS trip_date,
               COUNT(*) AS total_trips,
               COUNT(*) FILTER (
                   WHERE station_id_start IS NULL OR station_id_end IS NULL
               ) AS missing_trips
        FROM read_parquet(?)
        WHERE isfinite(time_start)
        GROUP BY trip_date
        ORDER BY trip_date
        """,
        [timezone, str(trips_path)],
    ).fetchall()


def days_with_missing_station_ids(
    city_dir: str | Path, n: int = 1, *, timezone: str = "UTC"
) -> tuple[list[date], float | None]:
    """Return the trip start dates with at least n incomplete trips and their ratio.

    A trip is incomplete when its start or end station ID is missing.
    The denominator counts both the earliest and latest trip start dates.
    Return None for the ratio when there are no usable trip start dates.
    """
    if n < 1:
        raise ValueError("n must be at least 1")

    with duckdb.connect() as con:
        daily = _daily_trip_counts(con, Path(city_dir) / "trips.parquet", timezone)
    if not daily:
        return [], None

    dates = [day for day, _, missing in daily if missing >= n]
    elapsed_days = (daily[-1][0] - daily[0][0]).days + 1
    return dates, len(dates) / elapsed_days


def plot_daily_missing_station_id_share(
    data_dir: str | Path, cities: Sequence[str] = ("bergamo", "heidelberg", "karlsruhe"),
) -> Axes:
    """Plot the daily share of trips missing either station ID for each city.

    Pass the data directory and, optionally, a sequence of city folder names.
    Dates use the city's timezone from cities.parquet. Days with no recorded
    trips appear as gaps. Return the axes for notebook display or customization.
    """
    data_dir = Path(data_dir)
    series = []
    with duckdb.connect() as con:
        for city in cities:
            city_dir = data_dir / city
            name, timezone = con.execute(
                "SELECT name, timezone FROM read_parquet(?)",
                [str(city_dir / "cities.parquet")],
            ).fetchall()[0]
            daily = _daily_trip_counts(con, city_dir / "trips.parquet", timezone)
            if daily:
                first_day, last_day = daily[0][0], daily[-1][0]
                calendar = [
                    first_day + timedelta(days=offset)
                    for offset in range((last_day - first_day).days + 1)
                ]
                share_by_day = {day: missing / total for day, total, missing in daily}
                shares = [share_by_day.get(day, nan) for day in calendar]
                series.append((name, calendar, shares))

    _, ax = plt.subplots(figsize=(10, 4), layout="constrained")
    for name, dates, shares in series:
        ax.plot(
            date2num(dates), shares, label=name, linewidth=1.2, marker=".", markersize=2
        )
    locator = AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(ConciseDateFormatter(locator))
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=1))
    ax.set(
        title="Trips missing a station ID, by day",
        xlabel="Trip start date (local time)",
        ylabel="Share missing either station ID",
        ylim=(0, 1),
    )
    ax.grid(axis="y", alpha=0.25)
    if series:
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.22), ncols=3)
    return ax
