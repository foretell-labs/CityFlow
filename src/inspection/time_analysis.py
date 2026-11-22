"""Analyze the timing of recorded station status updates."""

from collections.abc import Sequence
from math import isfinite
from pathlib import Path
from typing import Literal

import duckdb
import numpy as np
from matplotlib import pyplot as plt
from matplotlib.axes import Axes
from matplotlib.dates import AutoDateLocator, ConciseDateFormatter, date2num
from matplotlib.ticker import PercentFormatter
from pandas import DataFrame

from src.inspection.station_status import station_rack_summary

_STATION_STATUS_HISTORY = """
    status_updates AS (
        SELECT * FROM read_parquet(?)
        UNION ALL BY NAME
        -- Support older files without a maintenance flag.
        SELECT NULL::BOOLEAN AS maintenance WHERE FALSE
    ), station_history AS (
        SELECT station_id, time, bikes_available_to_rent,
               LEAD(time) OVER chronological AS next_time,
               COALESCE(
                   LAST_VALUE(maintenance IGNORE NULLS) OVER chronological, FALSE
               ) AS in_maintenance
        FROM status_updates
        WHERE isfinite(time) AND station_id IS NOT NULL
        WINDOW chronological AS (
            PARTITION BY station_id ORDER BY time
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )
    )
"""


_STATION_RISK_STATES = """
    selected_stations AS (
        SELECT DISTINCT id
        FROM read_parquet(?)
        WHERE id IS NOT NULL
          AND COALESCE(list_contains(?::BIGINT[], id), TRUE)
    ), risk_states AS (
        SELECT station_id, time,
               CASE WHEN NOT in_maintenance AND bikes_available_to_rent >= 0
                    THEN bikes_available_to_rent <= 2 END AS at_risk
        FROM station_history
        JOIN selected_stations ON station_id = id
    )
"""


_STATION_GROUP_COLORS = (("small", "tab:blue"), ("big", "tab:orange"))


def _station_ids_with_dimension(stations: DataFrame, dimension: str) -> list[int]:
    return stations[stations["dimension"].eq(dimension)]["station_id"].tolist()


def _station_ids_for_group(
    city_dir: Path, station_group: Literal["all", "small", "big"]
) -> list[int] | None:
    if station_group == "all":
        return None

    selected_ids = _station_ids_with_dimension(
        station_rack_summary(city_dir), station_group
    )
    if not selected_ids:
        raise ValueError(f"No {station_group} stations in {city_dir.name}")
    return selected_ids


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
    selected_ids = _station_ids_for_group(city_dir, station_group)

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


def hourly_shortage_recoveries(
    city_dir: str | Path, station_group: Literal["all", "small", "big"] = "all"
) -> DataFrame:
    """Count recorded recoveries by the local hour of the second update.

    A recovery is a move from at most two rentable bikes to at least three
    between consecutive updates for the same station. Maintenance and missing
    or negative counts interrupt the sequence. Counts pool all observed dates.
    Divide by the number of unique stations in the selected group.
    """
    if station_group not in ("all", "small", "big"):
        raise ValueError("station_group must be 'all', 'small', or 'big'")

    city_dir = Path(city_dir)
    selected_ids = _station_ids_for_group(city_dir, station_group)
    return _hourly_shortage_recoveries(city_dir, selected_ids)


def _hourly_shortage_recoveries(
    city_dir: Path, selected_ids: list[int] | None
) -> DataFrame:
    with duckdb.connect() as con:
        (city_timezone,) = con.execute(
            "SELECT timezone FROM read_parquet(?)",
            [str(city_dir / "cities.parquet")],
        ).fetchall()[0]

        return con.execute(
            f"""
            WITH {_STATION_STATUS_HISTORY}, {_STATION_RISK_STATES},
            transitions AS (
                SELECT time, at_risk,
                       LAG(at_risk) OVER (PARTITION BY station_id ORDER BY time)
                           AS previous_at_risk
                FROM risk_states
            ), recoveries_by_hour AS (
                SELECT hour(timezone(?, to_timestamp(time))) AS local_hour,
                       COUNT(*) AS recoveries
                FROM transitions
                WHERE previous_at_risk AND NOT at_risk
                GROUP BY local_hour
            )
            SELECT hours.local_hour,
                   COALESCE(r.recoveries, 0) AS recoveries,
                   COALESCE(r.recoveries, 0) /
                       NULLIF((SELECT COUNT(*) FROM selected_stations), 0)
                       AS recoveries_per_station
            FROM range(24) AS hours(local_hour)
            LEFT JOIN recoveries_by_hour r USING (local_hour)
            ORDER BY hours.local_hour
            """,
            [
                str(city_dir / "station_status.parquet"),
                str(city_dir / "stations.parquet"),
                selected_ids,
                city_timezone,
            ],
        ).df()


def plot_hourly_shortage_recoveries(city_dir: str | Path) -> Axes:
    """Compare hourly recoveries per station for small and big stations."""
    city_dir = Path(city_dir)
    stations = station_rack_summary(city_dir)

    _, ax = plt.subplots(figsize=(11, 4), layout="constrained")
    for group, color in _STATION_GROUP_COLORS:
        selected_ids = _station_ids_with_dimension(stations, group)
        recoveries = _hourly_shortage_recoveries(city_dir, selected_ids)
        label = f"{group.title()} stations"
        if not selected_ids:
            label += " (none)"
        ax.plot(
            recoveries["local_hour"].to_numpy(),
            recoveries["recoveries_per_station"].to_numpy(),
            marker="o",
            color=color,
            label=label,
        )
    ax.set(
        title=f"{city_dir.name.title()} shortage recoveries",
        xlabel="Local hour of day",
        ylabel="Recoveries per station",
        xticks=range(24),
        ylim=(0, None),
    )
    ax.grid(axis="y", alpha=0.25)
    ax.legend()
    return ax


def shortage_durations(
    city_dir: str | Path,
    station_group: Literal["all", "small", "big"] = "all",
    *,
    collection_gaps: Sequence[tuple[float, float]] = (),
) -> DataFrame:
    """Return one row per complete recorded shortage episode for each station.

    Use the first update with at most two rentable bikes after a healthy update
    as the start, and the next update with at least three as the recovery.
    Maintenance and invalid counts break the history and leave the affected
    episode without a known start or end.

    Collection gaps are (last observed time, first resumed time) in Unix
    seconds. Exclude an episode if the interval from its last healthy update
    before onset to its recovery overlaps one of these gaps.
    """
    if station_group not in ("all", "small", "big"):
        raise ValueError("station_group must be 'all', 'small', or 'big'")

    for start, end in collection_gaps:
        if not isfinite(start) or not isfinite(end) or start >= end:
            raise ValueError("Collection gaps must have finite, increasing timestamps")

    city_dir = Path(city_dir)
    selected_ids = _station_ids_for_group(city_dir, station_group)
    with duckdb.connect() as con:
        return con.execute(
            f"""
            WITH {_STATION_STATUS_HISTORY}, {_STATION_RISK_STATES},
            gaps AS (
                SELECT UNNEST(?::DOUBLE[]) AS gap_start,
                       UNNEST(?::DOUBLE[]) AS gap_end
            ), state_changes AS (
                SELECT station_id, time, at_risk,
                       LAG(at_risk) OVER chronological AS previous_at_risk,
                       LAG(time) OVER chronological AS previous_time
                FROM risk_states
                WINDOW chronological AS (PARTITION BY station_id ORDER BY time)
                QUALIFY at_risk IS DISTINCT FROM previous_at_risk
            ), episode_bounds AS (
                SELECT *,
                       LEAD(time) OVER chronological AS recovery_time,
                       LEAD(at_risk) OVER chronological AS next_at_risk
                FROM state_changes
                WINDOW chronological AS (PARTITION BY station_id ORDER BY time)
            )
            SELECT station_id,
                   timezone('UTC', to_timestamp(time)) AS shortage_start_utc,
                   timezone('UTC', to_timestamp(recovery_time)) AS recovery_utc,
                   (recovery_time - time) / 3600 AS duration_hours
            FROM episode_bounds
            WHERE at_risk AND NOT previous_at_risk AND NOT next_at_risk
              AND recovery_time > time
              AND NOT EXISTS (
                  SELECT 1 FROM gaps
                  WHERE gap_start < recovery_time AND gap_end > previous_time
              )
            ORDER BY station_id, time
            """,
            [
                str(city_dir / "station_status.parquet"),
                str(city_dir / "stations.parquet"),
                selected_ids,
                [start for start, _ in collection_gaps],
                [end for _, end in collection_gaps],
            ],
        ).df()


def plot_shortage_duration_distribution(
    city_dir: str | Path,
    *,
    collection_gaps: Sequence[tuple[float, float]] = (),
) -> Axes:
    """Compare duration-bin shares, normalized within each station group."""
    city_dir = Path(city_dir)
    episodes = shortage_durations(city_dir, collection_gaps=collection_gaps)
    stations = station_rack_summary(city_dir)
    bin_edges = [0, 0.25, 0.5, 1, 2, 4, 8, 24, np.inf]
    bin_labels = [
        "<15 min",
        "15-30 min",
        "30-60 min",
        "1-2 h",
        "2-4 h",
        "4-8 h",
        "8-24 h",
        "24+ h",
    ]
    bin_positions = np.arange(len(bin_labels))
    bar_width = 0.38

    _, ax = plt.subplots(figsize=(10, 4), layout="constrained")
    for index, (group, color) in enumerate(_STATION_GROUP_COLORS):
        selected_ids = _station_ids_with_dimension(stations, group)
        durations = episodes[episodes["station_id"].isin(selected_ids)][
            "duration_hours"
        ]
        label = f"{group.title()} stations"
        if durations.empty:
            label += " (no episodes)"
            shares = np.full(len(bin_labels), np.nan)
        else:
            counts, _ = np.histogram(durations.to_numpy(), bins=bin_edges)
            shares = counts / len(durations)
        ax.bar(
            bin_positions + (index - 0.5) * bar_width,
            shares,
            width=bar_width,
            label=label,
            color=color,
        )
    ax.set(
        title=f"{city_dir.name.title()} shortage durations",
        xlabel="Shortage duration",
        ylabel="Share of shortage episodes",
        ylim=(0, None),
    )
    ax.set_xticks(bin_positions, bin_labels)
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=1))
    ax.grid(axis="y", alpha=0.25)
    ax.set_axisbelow(True)
    ax.legend()
    return ax


def station_shortage_hours(city_dir: str | Path) -> DataFrame:
    """Add active_hours and shortage_hours to the city's station rack summary.

    Active hours sum the time between updates outside maintenance. Shortage
    hours sum the active intervals that start with fewer than three rentable
    bikes. A maintenance flag applies until the next explicit flag for that
    station. If no flag has been reported, treat the station as active.
    Intervals with missing bike counts contribute no shortage time, and the
    last update ends the span. Stations without usable timestamps have missing
    values for both metrics.
    """
    city_dir = Path(city_dir)
    summary = station_rack_summary(city_dir)
    with duckdb.connect() as con:
        hours = con.execute(
            f"""
            WITH {_STATION_STATUS_HISTORY}
            SELECT station_id,
                   COALESCE(SUM(next_time - time) FILTER (
                       WHERE NOT in_maintenance
                   ), 0) / 3600 AS active_hours,
                   COALESCE(SUM(next_time - time) FILTER (
                       WHERE NOT in_maintenance AND bikes_available_to_rent < 3
                   ), 0) / 3600 AS shortage_hours
            FROM station_history
            GROUP BY station_id
            """,
            [str(city_dir / "station_status.parquet")],
        ).df()
    return summary.merge(hours, on="station_id", how="left")
