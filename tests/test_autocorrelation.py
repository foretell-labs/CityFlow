"""Tests for forecast error rates and autocorrelation."""

import numpy as np
from pandas import DataFrame

from city_flow.modelling.autocorrelation import (
    error_rate_by_time,
    pearson_autocorrelation,
)


def test_error_rate_by_time_groups_forecasts_and_skips_missing_values():
    pairs = DataFrame(
        {
            "issue_time": [1350, 0, 0, 0, 1350, None, 3600],
            "predicted_at_risk": [1, 1, 0, 1, 0, 0, None],
            "actual_at_risk": [1, 0, 0, None, 0, 1, 0],
        }
    )

    result = error_rate_by_time(pairs)

    assert result["issue_time"].tolist() == [0, 1350]
    assert result["error_rate"].tolist() == [0.5, 0.0]
    assert result["n_forecasts"].tolist() == [2, 2]


def test_autocorrelation_uses_elapsed_time_on_an_irregular_grid():
    pairs = DataFrame(
        {
            "issue_time": [5400, 0, 3900, 1500],
            "predicted_at_risk": [0, 0, 0, 0],
            "actual_at_risk": [0, 0, 1, 1],
        }
    )

    result = pearson_autocorrelation(pairs, lags_seconds=[0, 1500, 2400, 3600])

    assert result["lag_seconds"].tolist() == [0, 1500, 2400, 3600]
    assert result["n_pairs"].tolist() == [4, 2, 1, 0]
    np.testing.assert_allclose(result["autocorrelation"], [1, -1, np.nan, np.nan])
