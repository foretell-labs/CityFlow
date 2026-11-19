import tempfile
import unittest
from pathlib import Path

import duckdb

from src.inspection.station_status import station_status_mismatch_ratio


class StationStatusMismatchTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.city_dir = Path(temp_dir.name)

    def write_station_status(
        self, rows: list[tuple[int | None, int | None, int | None]]
    ):
        with duckdb.connect() as con:
            con.execute("""
                CREATE TABLE station_status (
                    bikes BIGINT,
                    booked_bikes BIGINT,
                    bikes_available_to_rent BIGINT
                )
            """)
            if rows:
                con.executemany("INSERT INTO station_status VALUES (?, ?, ?)", rows)
            con.table("station_status").write_parquet(
                str(self.city_dir / "station_status.parquet")
            )

    def test_counts_positive_and_negative_differences_once_each(self):
        self.write_station_status(
            [(8, 3, 5), (0, 0, 0), (6, 0, 6), (10, 1, 5), (3, 2, 4)]
        )

        self.assertEqual(station_status_mismatch_ratio(self.city_dir), 2 / 5)

    def test_missing_counts_stay_in_the_denominator(self):
        self.write_station_status([(None, 1, 0), (3, None, 3), (3, 0, None), (2, 0, 1)])

        self.assertEqual(station_status_mismatch_ratio(self.city_dir), 1 / 4)

    def test_empty_parquet_has_no_ratio(self):
        self.write_station_status([])

        self.assertIsNone(station_status_mismatch_ratio(self.city_dir))
