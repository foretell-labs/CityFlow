import tempfile
import unittest
from math import isnan, sqrt
from pathlib import Path

import duckdb
from pandas import isna

from city_flow.inspection.station_status import (
    SMALL_STATION_MAX_AVG_BIKES,
    station_rack_summary,
    station_status_mismatch_ratio,
)


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

    def test_rack_summary_uses_capacity_specific_metrics(self):
        cutoff = SMALL_STATION_MAX_AVG_BIKES
        spread = min(1, cutoff)
        south_low, south_high = cutoff - spread, cutoff + spread
        west_count = cutoff + 1
        with duckdb.connect() as con:
            con.sql("""
                SELECT * FROM (VALUES (1, 'North', 10), (1, 'North', 10),
                    (2, 'South', 0), (3, 'East', 8), (4, 'West', 0))
                AS stations(id, name, bike_racks)
            """).write_parquet(str(self.city_dir / "stations.parquet"))
            con.sql(
                """
                SELECT * FROM (VALUES
                    (1, 3, 7, 3), (1, 2, 5, 1), (1, 6, 5, 5), (1, NULL, 6, NULL),
                    (2, ?, 4, ?), (2, ?, 9, ?), (2, 11, NULL, NULL),
                    (4, ?, 3, ?))
                AS status(station_id, bikes, free_racks, bikes_available_to_rent)
                """,
                params=[
                    south_low,
                    south_low,
                    south_high,
                    south_high,
                    west_count,
                    west_count,
                ],
            ).write_parquet(str(self.city_dir / "station_status.parquet"))

        summary = station_rack_summary(self.city_dir)

        self.assertEqual(
            list(summary.columns),
            [
                "station_id",
                "station_name",
                "bike_racks",
                "rack_mismatch_ratio",
                "mean_available_bikes",
                "std_available_bikes",
                "dimension",
            ],
        )
        north, south, east, west = summary.itertuples(index=False, name=None)
        self.assertEqual(north[:5], (1, "North", 10, 0.5, 3.0))
        self.assertAlmostEqual(north[5], sqrt(8 / 3))
        self.assertEqual(south, (2, "South", 0, 0.0, cutoff, spread, "small"))
        self.assertEqual(east[:3], (3, "East", 8))
        self.assertTrue(all(isnan(value) for value in east[3:6]))
        self.assertTrue(isna(east[6]))
        self.assertEqual(west, (4, "West", 0, 0.0, west_count, 0.0, "big"))
