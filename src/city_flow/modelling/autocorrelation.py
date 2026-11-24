"""Analyze how forecast errors vary across issue times."""

from collections.abc import Iterable
from math import isfinite, nan

import numpy as np
from pandas import DataFrame, to_numeric


def error_rate_by_time(prediction_pairs: DataFrame) -> DataFrame:
    """Return the fraction of incorrect predictions at each issue time.

    Issue times are Unix timestamps in seconds. Rows missing an issue time,
    prediction, or actual label are skipped. The result includes the number
    of scored forecasts at each time.
    """
    scored = prediction_pairs[
        ["issue_time", "predicted_at_risk", "actual_at_risk"]
    ].dropna()
    issue_time = to_numeric(scored["issue_time"])
    if not np.isfinite(issue_time.to_numpy(dtype=float)).all():
        raise ValueError("issue_time must contain finite Unix timestamps")

    errors = scored["predicted_at_risk"].ne(scored["actual_at_risk"])
    return (
        errors.groupby(issue_time, sort=True)
        .agg(error_rate="mean", n_forecasts="size")
        .reset_index()
    )


def pearson_autocorrelation(
    prediction_pairs: DataFrame, lags_seconds: Iterable[int | float]
) -> DataFrame:
    """Correlate error rates at issue times t and t + lag for each supplied lag.

    Match exact elapsed times so missing issue times and irregular intervals
    stay in their original positions. Return NaN when there are fewer than
    two matched pairs or either side has no variation.
    """
    rates = error_rate_by_time(prediction_pairs).set_index("issue_time")["error_rate"]
    results = []
    for lag in lags_seconds:
        if not isfinite(lag) or lag < 0:
            raise ValueError("Lags must be finite and nonnegative")

        later_rates = rates.set_axis(rates.index.to_numpy() - lag)
        earlier, later = rates.align(later_rates, join="inner")
        correlation = nan
        if earlier.nunique() > 1 and later.nunique() > 1:
            correlation = earlier.corr(later, method="pearson")
        results.append((lag, len(earlier), correlation))

    return DataFrame(results, columns=["lag_seconds", "n_pairs", "autocorrelation"])
