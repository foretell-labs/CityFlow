"""Analyze the timing of recorded station status updates."""

from pathlib import Path
from typing import Literal

import duckdb
from matplotlib import pyplot as plt
from matplotlib.axes import Axes
from matplotlib.dates import AutoDateLocator, ConciseDateFormatter, date2num
from pandas import DataFrame

from src.inspection.station_status import station_rack_summary


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


def plot_station_status_by_hour_of_day(
    city_dir: str | Path,
    station_group: Literal["all", "small", "big"] = "all",
    confidence: float = 0.8,
) -> tuple[Axes, Axes]:
    """Plot two profiles with one point for each local hour of the day.

    Lines show means and medians. The confidence value sets the central percentile
    band from 0.5 - confidence / 2 to 0.5 + confidence / 2.
    Rentable bike counts are summarized across updates with a count.
    The station_group filter uses the dimension from station_rack_summary.
    Update rates are divided by the selected station count and summarized
    across dates with city data, including zeros when the group is quiet.
    """
    if station_group not in ("all", "small", "big"):
        raise ValueError("station_group must be 'all', 'small', or 'big'")
    if not 0 <= confidence <= 1:
        raise ValueError("confidence must be between 0 and 1")

    lower = 0.5 - confidence / 2
    upper = 0.5 + confidence / 2
    quantiles = [lower, 0.5, upper]
    city_dir = Path(city_dir)
    selected_ids = None
    if station_group != "all":
        summary = station_rack_summary(city_dir)
        # pyrefly: ignore[missing-attribute]
        selected_ids = summary.loc[
            summary["dimension"].eq(station_group), "station_id"
        ].tolist()
        if not selected_ids:
            raise ValueError(f"No {station_group} stations in {city_dir.name}")

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
            selected_stations AS (
                SELECT id
                FROM stations
                WHERE COALESCE(list_contains(?::BIGINT[], id), TRUE)
            ),
            city_updates AS (
                SELECT t.station_id,
                       timezone(?, to_timestamp(t.time)) AS local_time,
                       t.bikes_available_to_rent
                FROM read_parquet(?) t
                JOIN stations s ON t.station_id = s.id
                WHERE isfinite(t.time)
            ),
            updates AS (
                SELECT u.local_time, u.bikes_available_to_rent
                FROM city_updates u
                JOIN selected_stations s ON u.station_id = s.id
            ),
            hours AS (
                SELECT local_hour FROM range(24) AS h(local_hour)
            ),
            bike_profile AS (
                SELECT hour(local_time) AS local_hour,
                       AVG(bikes_available_to_rent) AS mean_bikes,
                       QUANTILE_CONT(bikes_available_to_rent, ?::DOUBLE[])
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
                       AVG(COALESCE(d.update_count, 0)) AS mean_updates,
                       QUANTILE_CONT(COALESCE(d.update_count, 0), ?::DOUBLE[])
                           AS update_percentiles
                FROM (
                    SELECT DISTINCT CAST(local_time AS DATE) AS local_day
                    FROM city_updates
                ) days
                CROSS JOIN hours h
                LEFT JOIN daily_updates d
                    ON d.local_day = days.local_day AND d.local_hour = h.local_hour
                GROUP BY h.local_hour
            )
            SELECT hours.local_hour,
                   b.mean_bikes,
                   u.mean_updates / totals.station_count AS mean_updates_per_station,
                   b.bike_percentiles[1] AS bikes_lower,
                   b.bike_percentiles[2] AS median_bikes,
                   b.bike_percentiles[3] AS bikes_upper,
                   u.update_percentiles[1] / totals.station_count AS updates_lower,
                   u.update_percentiles[2] / totals.station_count AS median_updates_per_station,
                   u.update_percentiles[3] / totals.station_count AS updates_upper
            FROM hours
            CROSS JOIN (SELECT COUNT(*) AS station_count FROM selected_stations) totals
            LEFT JOIN bike_profile b USING (local_hour)
            LEFT JOIN update_profile u USING (local_hour)
            ORDER BY hours.local_hour
            """,
            [
                str(city_dir / "stations.parquet"),
                selected_ids,
                city_timezone,
                str(city_dir / "station_status.parquet"),
                quantiles,
                quantiles,
            ],
        ).df()

    figure, (bikes_ax, updates_ax) = plt.subplots(
        2, 1, sharex=True, figsize=(11, 6), layout="constrained"
    )
    hours = profile["local_hour"].to_numpy()
    (bikes_line,) = bikes_ax.plot(
        hours, profile["median_bikes"].to_numpy(), marker="o", label="Median"
    )
    bikes_ax.plot(hours, profile["mean_bikes"].to_numpy(), linestyle="--", label="Mean")
    bikes_ax.fill_between(
        hours,
        profile["bikes_lower"].to_numpy(),
        profile["bikes_upper"].to_numpy(),
        color=bikes_line.get_color(),
        alpha=0.2,
    )
    bikes_ax.set(title="Rentable bikes at recorded updates", ylabel="Rentable bikes")
    (updates_line,) = updates_ax.plot(
        hours,
        profile["median_updates_per_station"].to_numpy(),
        marker="o",
        label="Median",
    )
    updates_ax.plot(
        hours,
        profile["mean_updates_per_station"].to_numpy(),
        linestyle="--",
        label="Mean",
    )
    updates_ax.fill_between(
        hours,
        profile["updates_lower"].to_numpy(),
        profile["updates_upper"].to_numpy(),
        color=updates_line.get_color(),
        alpha=0.2,
    )
    updates_ax.set(
        title="Station status updates",
        xlabel=f"Hour of day ({city_timezone})",
        ylabel="Updates per station",
        xticks=range(24),
    )
    for ax in (bikes_ax, updates_ax):
        ax.grid(axis="y", alpha=0.25)
        ax.legend()
    figure.suptitle(
        f"{city_name} {station_group} stations by hour "
        f"({lower:.1%} to {upper:.1%} percentile band)"
    )
    return bikes_ax, updates_ax


def station_shortage_hours(city_dir: str | Path) -> DataFrame:
    """Add active_hours and shortage_hours to the city's station rack summary.

    Active hours are the span from the first to the last valid timestamp.
    Shortage hours sum the intervals starting with fewer than three rentable
    bikes. Each count applies until the next update. Intervals with missing
    counts contribute no shortage time, and the last update ends the span.
    Stations without usable timestamps have missing values for both metrics.
    """
    city_dir = Path(city_dir)
    summary = station_rack_summary(city_dir)
    with duckdb.connect() as con:
        hours = con.execute(
            """
            WITH intervals AS (
                SELECT station_id, time, bikes_available_to_rent,
                       LEAD(time) OVER (PARTITION BY station_id ORDER BY time) AS next_time
                FROM read_parquet(?)
                WHERE isfinite(time) AND station_id IS NOT NULL
            )
            SELECT station_id,
                   (MAX(time) - MIN(time)) / 3600 AS active_hours,
                   COALESCE(SUM(next_time - time) FILTER (
                       WHERE bikes_available_to_rent < 3
                   ), 0) / 3600 AS shortage_hours
            FROM intervals
            GROUP BY station_id
            """,
            [str(city_dir / "station_status.parquet")],
        ).df()
    return summary.merge(hours, on="station_id", how="left")
