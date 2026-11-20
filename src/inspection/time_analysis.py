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


def plot_station_status_by_hour_of_day(city_dir: str | Path) -> tuple[Axes, Axes]:
    """Plot two profiles with one point for each local hour of the day.

    Points show medians and bands span the 10th to 90th percentiles.
    Rentable bike counts are summarized across updates with a count.
    Update rates are summarized across local dates with city data,
    including zeros for quiet hours, and divided by the station count.
    """
    city_dir = Path(city_dir)
    with duckdb.connect() as con:
        city_name, city_timezone = con.execute(
            "SELECT name, timezone FROM read_parquet(?)",
            [str(city_dir / "cities.parquet")],
        ).fetchall()[0]

        profile = con.execute(
            """
            WITH stations AS (
                SELECT DISTINCT id FROM read_parquet(?) WHERE id IS NOT NULL
            ),
            updates AS (
                SELECT timezone(?, to_timestamp(t.time)) AS local_time,
                       t.bikes_available_to_rent
                FROM read_parquet(?) t
                JOIN stations s ON t.station_id = s.id
                WHERE isfinite(t.time)
            ),
            hours AS (
                SELECT local_hour FROM range(24) AS h(local_hour)
            ),
            bike_profile AS (
                SELECT hour(local_time) AS local_hour,
                       QUANTILE_CONT(bikes_available_to_rent, [0.1, 0.5, 0.9])
                           AS bike_percentiles
                FROM updates
                GROUP BY local_hour
            ),
            daily_updates AS (
                SELECT CAST(local_time AS DATE) AS local_day,
                       hour(local_time) AS local_hour,
                       COUNT(*) AS update_count
                FROM updates
                GROUP BY local_day, local_hour
            ),
            update_profile AS (
                SELECT h.local_hour,
                       QUANTILE_CONT(COALESCE(d.update_count, 0), [0.1, 0.5, 0.9])
                           AS update_percentiles
                FROM (SELECT DISTINCT local_day FROM daily_updates) days
                CROSS JOIN hours h
                LEFT JOIN daily_updates d
                    ON d.local_day = days.local_day AND d.local_hour = h.local_hour
                GROUP BY h.local_hour
            )
            SELECT hours.local_hour,
                   b.bike_percentiles[1] AS bikes_p10,
                   b.bike_percentiles[2] AS median_bikes,
                   b.bike_percentiles[3] AS bikes_p90,
                   u.update_percentiles[1] / totals.station_count AS updates_p10,
                   u.update_percentiles[2] / totals.station_count AS median_updates_per_station,
                   u.update_percentiles[3] / totals.station_count AS updates_p90
            FROM hours
            CROSS JOIN (SELECT COUNT(*) AS station_count FROM stations) totals
            LEFT JOIN bike_profile b USING (local_hour)
            LEFT JOIN update_profile u USING (local_hour)
            ORDER BY hours.local_hour
            """,
            [
                str(city_dir / "stations.parquet"),
                city_timezone,
                str(city_dir / "station_status.parquet"),
            ],
        ).df()

    figure, (bikes_ax, updates_ax) = plt.subplots(
        2, 1, sharex=True, figsize=(11, 6), layout="constrained"
    )
    hours = profile["local_hour"].to_numpy()
    (bikes_line,) = bikes_ax.plot(hours, profile["median_bikes"].to_numpy(), marker="o")
    bikes_ax.fill_between(
        hours,
        profile["bikes_p10"].to_numpy(),
        profile["bikes_p90"].to_numpy(),
        color=bikes_line.get_color(),
        alpha=0.2,
    )
    bikes_ax.set(
        title="Rentable bikes at recorded updates", ylabel="Median rentable bikes"
    )
    (updates_line,) = updates_ax.plot(
        hours, profile["median_updates_per_station"].to_numpy(), marker="o"
    )
    updates_ax.fill_between(
        hours,
        profile["updates_p10"].to_numpy(),
        profile["updates_p90"].to_numpy(),
        color=updates_line.get_color(),
        alpha=0.2,
    )
    updates_ax.set(
        title="Station status updates",
        xlabel=f"Hour of day ({city_timezone})",
        ylabel="Median updates per station",
        xticks=range(24),
    )
    for ax in (bikes_ax, updates_ax):
        ax.grid(axis="y", alpha=0.25)
    figure.suptitle(
        f"{city_name} station activity by hour (median and 10th-90th percentiles)"
    )
    return bikes_ax, updates_ax
