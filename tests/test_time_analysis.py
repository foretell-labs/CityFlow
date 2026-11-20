import tempfile
import unittest
from math import isnan
from pathlib import Path

import duckdb
import numpy as np
from matplotlib import pyplot as plt
from pandas import Timestamp

from src.inspection.time_analysis import (
    hourly_station_status_changes,
    plot_station_status_by_hour_of_day,
)


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

    def test_profiles_group_local_hours_and_normalize_over_observed_days(self):
        with duckdb.connect() as con:
            con.sql("""
                SELECT 'Example' AS name, 'Europe/Berlin' AS timezone
            """).write_parquet(str(self.city_dir / "cities.parquet"))
            con.sql("""
                SELECT station_id, epoch(observed_at) AS time, bikes_available_to_rent
                FROM (VALUES
                    (1, TIMESTAMP '2022-12-31 23:10:00', 1),
                    (1, TIMESTAMP '2022-12-31 23:20:00', 3),
                    (2, TIMESTAMP '2023-01-01 00:01:00', NULL),
                    (2, TIMESTAMP '2023-01-02 23:15:00', 8),
                    (2, TIMESTAMP '2023-01-03 01:00:00', 0),
                    (2, TIMESTAMP '2023-01-03 23:10:00', NULL),
                    (99, TIMESTAMP '2023-01-05 00:00:00', 100),
                    (1, NULL, 100)
                ) AS updates(station_id, observed_at, bikes_available_to_rent)
            """).write_parquet(str(self.city_dir / "station_status.parquet"))

        bikes_ax, updates_ax = plot_station_status_by_hour_of_day(self.city_dir)
        self.addCleanup(plt.close, plt.gcf())
        bikes_line, bikes_mean_line = bikes_ax.get_lines()
        updates_line, updates_mean_line = updates_ax.get_lines()
        (bike_band,) = bikes_ax.collections
        (update_band,) = updates_ax.collections
        bikes = np.asarray(bikes_line.get_xydata(), dtype=float)
        updates = np.asarray(updates_line.get_xydata(), dtype=float)

        self.assertEqual(bikes[:, 0].tolist(), list(range(24)))
        self.assertEqual(updates[:, 0].tolist(), list(range(24)))
        self.assertEqual(bikes[0, 1], 3.0)
        self.assertTrue(isnan(bikes[1, 1]))
        self.assertEqual(bikes[2, 1], 0.0)
        self.assertEqual(updates[:4, 1].tolist(), [1 / 3, 0.0, 0.0, 0.0])

        self.assertEqual(bikes_mean_line.get_label(), "Mean")
        self.assertEqual(updates_mean_line.get_label(), "Mean")
        bike_means = np.asarray(bikes_mean_line.get_xydata(), dtype=float)
        update_means = np.asarray(updates_mean_line.get_xydata(), dtype=float)
        self.assertEqual(bike_means[0, 1], 4.0)
        self.assertTrue(isnan(bike_means[1, 1]))
        np.testing.assert_allclose(update_means[:4, 1], [4 / 9, 1 / 9, 1 / 9, 0.0])

        bike_vertices = np.asarray(bike_band.get_paths()[0].vertices, dtype=float)
        update_vertices = np.asarray(update_band.get_paths()[0].vertices, dtype=float)
        bike_bounds = bike_vertices[bike_vertices[:, 0] == 0, 1]
        update_bounds = update_vertices[update_vertices[:, 0] == 0, 1]
        np.testing.assert_allclose([bike_bounds.min(), bike_bounds.max()], [1.4, 7])
        np.testing.assert_allclose(
            [update_bounds.min(), update_bounds.max()], [1 / 3, 0.6]
        )

        narrower_axes = plot_station_status_by_hour_of_day(
            self.city_dir, confidence=0.5
        )
        self.addCleanup(plt.close, plt.gcf())
        for ax, expected in zip(narrower_axes, ([2.0, 5.5], [1 / 3, 0.5]), strict=True):
            (band,) = ax.collections
            vertices = np.asarray(band.get_paths()[0].vertices, dtype=float)
            bounds = vertices[vertices[:, 0] == 0, 1]
            np.testing.assert_allclose([bounds.min(), bounds.max()], expected)

    def test_profiles_reject_invalid_confidence(self):
        for value in (-0.1, 1.1, float("nan")):
            with (
                self.subTest(confidence=value),
                self.assertRaisesRegex(
                    ValueError, "confidence must be between 0 and 1"
                ),
            ):
                plot_station_status_by_hour_of_day(self.city_dir, confidence=value)

    def test_profiles_filter_stations_by_mean_rentable_bikes(self):
        with duckdb.connect() as con:
            con.sql("""
                SELECT 'Example' AS name, 'Europe/Berlin' AS timezone
            """).write_parquet(str(self.city_dir / "cities.parquet"))
            con.sql("""
                SELECT id, 'Station ' || id AS name, 0 AS bike_racks
                FROM range(1, 5) AS station(id)
            """).write_parquet(str(self.city_dir / "stations.parquet"))
            con.sql("""
                SELECT station_id, epoch(observed_at) AS time, bikes_available_to_rent,
                       bikes_available_to_rent AS bikes, 0 AS free_racks
                FROM (VALUES
                    (1, TIMESTAMP '2023-01-01 23:10:00', 5),
                    (1, TIMESTAMP '2023-01-01 23:20:00', 7),
                    (3, TIMESTAMP '2023-01-01 23:30:00', 2),
                    (2, TIMESTAMP '2023-01-02 23:10:00', 20),
                    (2, TIMESTAMP '2023-01-02 23:20:00', 22),
                    (2, TIMESTAMP '2023-01-03 23:10:00', 24)
                ) AS updates(station_id, observed_at, bikes_available_to_rent)
            """).write_parquet(str(self.city_dir / "station_status.parquet"))

        small_bikes, small_updates = plot_station_status_by_hour_of_day(
            self.city_dir, station_group="small"
        )
        self.addCleanup(plt.close, plt.gcf())
        big_bikes, big_updates = plot_station_status_by_hour_of_day(
            self.city_dir, station_group="big"
        )
        self.addCleanup(plt.close, plt.gcf())

        self.assertEqual(np.asarray(small_bikes.lines[0].get_xydata())[0, 1], 5)
        self.assertEqual(np.asarray(big_bikes.lines[0].get_xydata())[0, 1], 22)
        self.assertEqual(np.asarray(small_updates.lines[0].get_xydata())[0, 1], 0)
        self.assertEqual(np.asarray(big_updates.lines[0].get_xydata())[0, 1], 1)

        vertices = np.asarray(small_updates.collections[0].get_paths()[0].vertices)
        upper = vertices[vertices[:, 0] == 0, 1].max()
        self.assertAlmostEqual(float(upper), 1.2)
