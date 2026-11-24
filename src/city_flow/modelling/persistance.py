"""Predict a station's shortage risk by carrying forward its latest status."""

from math import isfinite, sqrt
from pathlib import Path
from statistics import NormalDist
from typing import TypedDict

import duckdb
import numpy as np
from matplotlib import pyplot as plt
from matplotlib.axes import Axes
from pandas import DataFrame
from sklearn.metrics import confusion_matrix

_AT_RISK_SQL = "CAST(bikes_available_to_rent <= 2 AS INTEGER)"


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
            f"""
            SELECT {_AT_RISK_SQL} AS at_risk
            FROM read_parquet(?)
            WHERE station_id = ? AND time <= ?
            ORDER BY time DESC
            LIMIT 1
            """,
            [str(status_path), station_id, time],
        ).fetchall()
    return rows[0][0] if rows else None


def build_persistence_evaluation(
    city_dir: str | Path, evaluation: DataFrame
) -> DataFrame:
    """Pair hourly persistence predictions with the status two hours later.

    Use UTC hours between the first and last evaluation timestamps, keeping
    pairs whose issue and target are both on that grid. Latest-update lookups
    can use earlier history. Keep the source timestamps and leave unavailable
    statuses missing for later scoring.
    """
    city_dir = Path(city_dir)
    with duckdb.connect() as con:
        con.register("evaluation_status", evaluation)
        first_hour, last_hour = con.execute("""
            SELECT CEIL(MIN(time) / 3600)::BIGINT * 3600,
                   FLOOR(MAX(time) / 3600)::BIGINT * 3600
            FROM evaluation_status
            WHERE isfinite(time)
        """).fetchall()[0]
        return con.execute(
            f"""
            WITH grid AS (
                SELECT DISTINCT id AS station_id, hour_time
                FROM read_parquet(?)
                CROSS JOIN range(?, ? + 3600, 3600) AS hours(hour_time)
                WHERE id IS NOT NULL
            ), statuses AS (
                SELECT station_id, time, {_AT_RISK_SQL} AS at_risk
                FROM read_parquet(?)
                WHERE time <= ?
            ), hourly AS (
                SELECT g.station_id, g.hour_time, s.time AS update_time, s.at_risk
                FROM grid g
                ASOF LEFT JOIN statuses s
                    ON g.station_id = s.station_id AND g.hour_time >= s.time
            ), pairs AS (
                SELECT station_id,
                       hour_time AS issue_time,
                       LEAD(hour_time, 2) OVER station_hours AS target_time,
                       update_time AS issue_update_time,
                       LEAD(update_time, 2) OVER station_hours AS target_update_time,
                       at_risk AS predicted_at_risk,
                       LEAD(at_risk, 2) OVER station_hours AS actual_at_risk
                FROM hourly
                WINDOW station_hours AS (PARTITION BY station_id ORDER BY hour_time)
            )
            SELECT * FROM pairs
            WHERE target_time IS NOT NULL
            ORDER BY issue_time, station_id
            """,
            [
                str(city_dir / "stations.parquet"),
                first_hour,
                last_hour,
                str(city_dir / "station_status.parquet"),
                last_hour,
            ],
        ).df()


class PersistenceMetrics(TypedDict):
    tn: int
    fp: int
    fn: int
    tp: int
    precision: float
    recall: float
    f1: float
    accuracy: float
    new_shortage_rate: float
    confidence_intervals: dict[str, tuple[float, float]]


def _wilson_interval(successes: int, total: int, z: float) -> tuple[float, float]:
    """Return a Wilson score interval for a binomial proportion."""
    if total == 0:
        return float("nan"), float("nan")

    proportion = successes / total
    z_squared = z * z
    scale = 1 + z_squared / total
    center = (proportion + z_squared / (2 * total)) / scale
    margin = z * sqrt((proportion * (1 - proportion) + z_squared / (4 * total)) / total)
    margin /= scale
    return max(0.0, center - margin), min(1.0, center + margin)


def evaluation_metrics(
    persistence_pairs: DataFrame, *, confidence: float = 0.95
) -> tuple[Axes, PersistenceMetrics]:
    """Return a confusion matrix plot, cell counts, and five benchmark metrics.

    Use 1 for shortage and 0 for healthy. Skip pairs with either label missing.
    Include Wilson confidence intervals assuming independent station-hours.
    For F1, transform the Wilson interval for TP / (TP + FP + FN).
    Undefined metrics and their interval endpoints are NaN. Apply any
    eligibility filters to the input before calling this function.
    """
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")

    scored = persistence_pairs[["actual_at_risk", "predicted_at_risk"]].dropna()
    if not scored.isin([0, 1]).to_numpy().all():
        raise ValueError("Both risk columns must contain only 0, 1, or missing values")

    if scored.empty:
        raise ValueError("Scored pairs are empty; cannot compute confusion matrix")
    else:
        counts = confusion_matrix(
            scored["actual_at_risk"].to_numpy(dtype=int),
            scored["predicted_at_risk"].to_numpy(dtype=int),
            labels=[0, 1],
        )
    tn, fp, fn, tp = map(int, counts.ravel())
    undefined = float("nan")
    z = -NormalDist().inv_cdf((1 - confidence) / 2)
    overlap_lower, overlap_upper = _wilson_interval(tp, tp + fp + fn, z)
    metrics: PersistenceMetrics = {
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "tp": tp,
        "precision": tp / (tp + fp) if tp + fp else undefined,
        "recall": tp / (tp + fn) if tp + fn else undefined,
        "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else undefined,
        "accuracy": (tp + tn) / len(scored) if len(scored) else undefined,
        "new_shortage_rate": fn / (tn + fn) if tn + fn else undefined,
        "confidence_intervals": {
            "precision": _wilson_interval(tp, tp + fp, z),
            "recall": _wilson_interval(tp, tp + fn, z),
            "f1": (
                2 * overlap_lower / (1 + overlap_lower),
                2 * overlap_upper / (1 + overlap_upper),
            ),
            "accuracy": _wilson_interval(tp + tn, len(scored), z),
            "new_shortage_rate": _wilson_interval(fn, tn + fn, z),
        },
    }

    row_totals = counts.sum(axis=1, keepdims=True)
    shares = np.divide(
        counts, row_totals, out=np.full(counts.shape, np.nan), where=row_totals > 0
    )
    _, ax = plt.subplots(figsize=(5.6, 4.4), layout="constrained")
    ax.imshow(shares, cmap="Blues", vmin=0, vmax=1)
    for (actual, predicted), count in np.ndenumerate(counts):
        share = shares[actual, predicted]
        percentage = "n/a" if np.isnan(share) else f"{share:.1%}"
        ax.text(
            predicted,
            actual,
            f"{count:,}\n{percentage}",
            ha="center",
            va="center",
            color="white" if share > 0.5 else "black",
        )
    labels = ["Healthy", "Shortage"]
    ax.set_xticks([0, 1], labels)
    ax.set_yticks([0, 1], labels)
    ax.set(
        title="Persistence confusion matrix",
        xlabel="Predicted state",
        ylabel="Actual state at +2 hours",
    )
    return ax, metrics
