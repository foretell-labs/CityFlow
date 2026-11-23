import tempfile
import unittest
from math import isnan
from pathlib import Path

import duckdb
from matplotlib import pyplot as plt
from pandas import DataFrame, isna

from city_flow.modelling.persistance import (
    build_persistence_evaluation,
    evaluation_metrics,
    predict_persistence,
)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.city_dir = Path(temp_dir.name)

        with duckdb.connect() as con:
            con.sql("""
                SELECT * FROM (VALUES
                    (1, 300.0, 1), (2, 190.0, 0), (1, 100.0, 5),
                    (1, 400.0, NULL), (1, 200.0, 2)
                ) AS statuses(station_id, time, bikes_available_to_rent)
            """).write_parquet(str(self.city_dir / "station_status.parquet"))

    def test_uses_latest_update_for_the_station_without_looking_ahead(self):
        self.assertEqual(predict_persistence(self.city_dir, 1, 199.5), 0)
        self.assertEqual(predict_persistence(self.city_dir, 1, 200), 1)
        self.assertEqual(predict_persistence(self.city_dir, 1, 350), 1)

    def test_missing_prior_update_or_latest_count_returns_none(self):
        self.assertIsNone(predict_persistence(self.city_dir, 1, 99))
        self.assertIsNone(predict_persistence(self.city_dir, 99, 350))
        self.assertIsNone(predict_persistence(self.city_dir, 1, 400))

    def test_rejects_nonfinite_prediction_time(self):
        with self.assertRaisesRegex(ValueError, "finite Unix timestamp"):
            predict_persistence(self.city_dir, 1, float("nan"))

    def test_builds_two_hour_evaluation_pairs_with_latest_updates(self):
        with duckdb.connect() as con:
            con.sql("""
                SELECT * FROM (VALUES (1), (1), (2), (3)) AS stations(id)
            """).write_parquet(str(self.city_dir / "stations.parquet"))
            statuses = con.sql("""
                SELECT * FROM (VALUES
                    (1, 3599.0, 5), (1, 3600.0, 4), (1, 7200.0, 2),
                    (1, 10801.0, 4), (1, 14400.0, NULL), (1, 14700.0, 9),
                    (1, 18000.0, 3), (2, 0.0, 0), (2, 14401.0, 5)
                ) AS events(station_id, time, bikes_available_to_rent)
            """)
            statuses.write_parquet(str(self.city_dir / "station_status.parquet"))
            evaluation = statuses.filter("time BETWEEN 3599 AND 14700").df()

        pairs = build_persistence_evaluation(self.city_dir, evaluation)

        self.assertEqual(pairs["station_id"].tolist(), [1, 2, 3, 1, 2, 3])
        self.assertEqual(pairs["issue_time"].tolist(), [3600] * 3 + [7200] * 3)
        self.assertEqual(pairs["target_time"].tolist(), [10800] * 3 + [14400] * 3)
        first_station = pairs[pairs["station_id"].eq(1)]
        self.assertEqual(first_station["issue_update_time"].tolist(), [3600, 7200])
        self.assertEqual(first_station["target_update_time"].tolist(), [7200, 14400])
        self.assertEqual(
            first_station["predicted_at_risk"].tolist(),
            [predict_persistence(self.city_dir, 1, t) for t in (3600, 7200)],
        )
        (
            first_label,
            last_label,
        ) = first_station["actual_at_risk"].tolist()
        self.assertEqual(first_label, predict_persistence(self.city_dir, 1, 10800))
        self.assertTrue(isna(last_label))
        second_station = pairs[pairs["station_id"].eq(2)]
        self.assertEqual(second_station["actual_at_risk"].tolist(), [1, 1])
        third_station = pairs[pairs["station_id"].eq(3)]
        self.assertTrue(third_station["predicted_at_risk"].isna().all())
        self.assertTrue(third_station["actual_at_risk"].isna().all())

    def test_evaluation_metrics_scores_only_complete_pairs(self):
        pairs = DataFrame(
            {
                "actual_at_risk": [0] * 5 + [1] * 5 + [None, 1],
                "predicted_at_risk": [0] * 3 + [1, 1, 0] + [1] * 4 + [1, None],
            },
            dtype="Int32",
        )

        ax, metrics = evaluation_metrics(pairs)
        self.addCleanup(plt.close, plt.gcf())

        self.assertEqual(
            metrics,
            {
                "tn": 3,
                "fp": 2,
                "fn": 1,
                "tp": 4,
                "precision": 2 / 3,
                "recall": 4 / 5,
                "f1": 8 / 11,
                "accuracy": 7 / 10,
                "new_shortage_rate": 1 / 4,
            },
        )
        self.assertEqual(
            [label.get_text() for label in ax.texts],
            ["3\n60.0%", "2\n40.0%", "1\n20.0%", "4\n80.0%"],
        )

    def test_evaluation_metrics_handles_a_missing_actual_class(self):
        pairs = DataFrame({"actual_at_risk": [0, 0], "predicted_at_risk": [0, 0]})

        ax, metrics = evaluation_metrics(pairs)
        self.addCleanup(plt.close, plt.gcf())

        self.assertEqual(metrics["accuracy"], 1)
        self.assertEqual(metrics["new_shortage_rate"], 0)
        for name in ("precision", "recall", "f1"):
            self.assertTrue(isnan(metrics[name]))
        self.assertEqual([label.get_text() for label in ax.texts[-2:]], ["0\nn/a"] * 2)

    def test_evaluation_metrics_raises_when_no_complete_pairs(self):
        pairs = DataFrame({"actual_at_risk": [None], "predicted_at_risk": [1]})

        with self.assertRaisesRegex(ValueError, "Scored pairs are empty"):
            evaluation_metrics(pairs)
