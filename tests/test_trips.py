import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

import duckdb

from src.inspection.trips import days_with_missing_station_ids


class MissingStationDaysTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.city_dir = Path(temp_dir.name)

    def write_trips(self, rows):
        with duckdb.connect() as con:
            con.execute("""
                CREATE TABLE trips (
                    time_start DOUBLE,
                    station_id_start INTEGER,
                    station_id_end INTEGER
                )
            """)
            con.executemany(
                "INSERT INTO trips VALUES (?, ?, ?)",
                [
                    (datetime.fromisoformat(start).timestamp() if start else None, origin, end)
                    for start, origin, end in rows
                ],
            )
            con.table("trips").write_parquet(str(self.city_dir / "trips.parquet"))

    def test_threshold_and_elapsed_days_include_the_full_trip_date_span(self):
        self.write_trips([
            ("2023-01-01T12:00:00+00:00", 1, 2),
            ("2023-01-03T08:00:00+00:00", None, 2),
            ("2023-01-03T09:00:00+00:00", None, None),
            ("2023-01-05T12:00:00+00:00", 1, None),
            ("2023-01-07T12:00:00+00:00", 1, 2),
            (None, None, None),
        ])

        self.assertEqual(
            days_with_missing_station_ids(self.city_dir),
            ([date(2023, 1, 3), date(2023, 1, 5)], 2 / 7),
        )
        self.assertEqual(
            days_with_missing_station_ids(self.city_dir, n=2),
            ([date(2023, 1, 3)], 1 / 7),
        )
        self.assertEqual(days_with_missing_station_ids(self.city_dir, n=3), ([], 0.0))

    def test_timezone_changes_the_date_span_at_midnight(self):
        self.write_trips([
            ("2023-01-01T22:30:00+00:00", 1, 2),
            ("2023-01-01T23:30:00+00:00", None, 2),
        ])

        self.assertEqual(
            days_with_missing_station_ids(self.city_dir), ([date(2023, 1, 1)], 1.0)
        )
        self.assertEqual(
            days_with_missing_station_ids(self.city_dir, timezone="Europe/Berlin"),
            ([date(2023, 1, 2)], 0.5),
        )

    def test_no_usable_trip_dates(self):
        self.write_trips([(None, None, 2)])

        self.assertEqual(days_with_missing_station_ids(self.city_dir), ([], None))
