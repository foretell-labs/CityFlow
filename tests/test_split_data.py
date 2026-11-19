import tempfile
import unittest
from pathlib import Path

import duckdb

from src.data_extraction.split_data import split_station_status_by_time


class StationStatusSplitTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.city_dir = Path(temp_dir.name)

    def write_status(self, query: str) -> None:
        with duckdb.connect() as con:
            con.sql(query).write_parquet(str(self.city_dir / "station_status.parquet"))

    def test_splits_observed_dates_without_splitting_a_day_between_frames(self):
        self.write_status("""
            SELECT 1 AS station_id, epoch(day) AS time
            FROM generate_series(DATE '2023-01-01', DATE '2023-01-12', INTERVAL 1 DAY)
                AS dates(day)
            WHERE day NOT BETWEEN DATE '2023-01-04' AND DATE '2023-01-05'
            UNION ALL
            SELECT 2, epoch(TIMESTAMP '2023-01-10 00:00:00')
            UNION ALL
            SELECT 3, epoch(TIMESTAMP '2023-01-10 23:59:00')
            UNION ALL
            SELECT 4, NULL
            ORDER BY time DESC
        """)

        train, evaluation, test = split_station_status_by_time(self.city_dir)

        self.assertEqual((len(train), len(evaluation), len(test)), (7, 3, 2))
        self.assertEqual(evaluation["station_id"].tolist(), [1, 2, 3])
        for frame in (train, evaluation, test):
            self.assertTrue(frame["time"].is_monotonic_increasing)

    def test_keeps_each_split_nonempty_with_three_observed_dates(self):
        self.write_status("""
            SELECT 1 AS station_id, epoch(day) AS time
            FROM generate_series(DATE '2023-01-01', DATE '2023-01-03', INTERVAL 1 DAY)
                AS dates(day)
        """)

        self.assertEqual(
            tuple(map(len, split_station_status_by_time(self.city_dir))), (1, 1, 1)
        )

    def test_requires_three_observed_dates(self):
        self.write_status("SELECT 1 AS station_id, 0.0 AS time")

        with self.assertRaisesRegex(ValueError, "three observed UTC dates"):
            split_station_status_by_time(self.city_dir)
