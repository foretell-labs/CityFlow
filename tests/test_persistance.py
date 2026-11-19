import tempfile
import unittest
from pathlib import Path

import duckdb

from src.modelling.persistance import predict_persistence


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
