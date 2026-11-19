import tempfile
import unittest
from pathlib import Path

import duckdb
from pandas import Timestamp

from src.inspection.time_analysis import hourly_station_status_changes


class HourlyStationStatusTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.city_dir = Path(temp_dir.name)

        with duckdb.connect() as con:
            con.sql("""
                SELECT * FROM (VALUES (1), (1), (2), (3)) AS stations(id)
            """).write_parquet(str(self.city_dir / "stations.parquet"))

    def test_counts_each_hour_including_gaps_and_uses_all_unique_stations(self):
        with duckdb.connect() as con:
            con.sql("""
                SELECT station_id, epoch(observed_at) AS time
                FROM (VALUES
                    (1, TIMESTAMP '2023-01-01 00:00:00'),
                    (2, TIMESTAMP '2023-01-01 00:59:59'),
                    (2, TIMESTAMP '2023-01-01 02:00:00'),
                    (99, TIMESTAMP '2023-01-01 03:00:00'),
                    (1, NULL)
                ) AS updates(station_id, observed_at)
            """).write_parquet(str(self.city_dir / "station_status.parquet"))

        hourly = hourly_station_status_changes(self.city_dir)

        self.assertEqual(
            list(hourly.itertuples(index=False, name=None)),
            [
                (Timestamp("2023-01-01 00:00:00"), 2, 2 / 3),
                (Timestamp("2023-01-01 01:00:00"), 0, 0.0),
                (Timestamp("2023-01-01 02:00:00"), 1, 1 / 3),
            ],
        )

    def test_no_recorded_updates_produces_an_empty_table(self):
        with duckdb.connect() as con:
            con.sql("""
                SELECT 1 AS station_id, 0.0 AS time WHERE FALSE
            """).write_parquet(str(self.city_dir / "station_status.parquet"))

        self.assertTrue(hourly_station_status_changes(self.city_dir).empty)

    def test_two_hour_intervals_are_aligned_and_include_empty_intervals(self):
        with duckdb.connect() as con:
            con.sql("""
                SELECT station_id, epoch(observed_at) AS time
                FROM (VALUES
                    (1, TIMESTAMP '2023-01-01 01:59:59'),
                    (1, TIMESTAMP '2023-01-01 02:00:00'),
                    (2, TIMESTAMP '2023-01-01 03:30:00'),
                    (2, TIMESTAMP '2023-01-01 06:00:00')
                ) AS updates(station_id, observed_at)
            """).write_parquet(str(self.city_dir / "station_status.parquet"))

        counts = hourly_station_status_changes(self.city_dir, deltaT=2)

        self.assertEqual(
            list(counts.itertuples(index=False, name=None)),
            [
                (Timestamp("2023-01-01 00:00:00"), 1, 1 / 3),
                (Timestamp("2023-01-01 02:00:00"), 2, 2 / 3),
                (Timestamp("2023-01-01 04:00:00"), 0, 0.0),
                (Timestamp("2023-01-01 06:00:00"), 1, 1 / 3),
            ],
        )

    def test_rejects_nonpositive_intervals(self):
        for hours in (0, -1):
            with (
                self.subTest(hours=hours),
                self.assertRaisesRegex(ValueError, "positive integer"),
            ):
                hourly_station_status_changes(self.city_dir, deltaT=hours)
