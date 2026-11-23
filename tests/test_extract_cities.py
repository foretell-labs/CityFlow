import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import duckdb

from city_flow.data_extraction import extract_cities


class ExtractCitiesTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.output_dir = Path(temp_dir.name) / "data"
        self.raw_dir = self.output_dir / "raw"
        self.raw_dir.mkdir(parents=True)

        self.write_csv(
            "cities.csv",
            "id,name\n1,Bergamo\n2,Heidelberg\n3,Other City\n",
        )
        self.write_csv(
            "stations.csv",
            "id,city_id,name\n10,1,North\n11,1,South\n20,2,Center\n30,3,West\n",
        )
        self.write_csv(
            "station_status.csv",
            "station_id,time,bikes\n"
            "10,1735689600,5\n10,1735693200,2\n11,1735689600,3\n"
            "20,1735689600,1\n30,1735689600,7\n99,1735689600,9\n",
        )
        self.write_csv(
            "trips.csv",
            "bike_id,city_id,station_id_start,station_id_end\n"
            "100,1,10,11\n200,2,20,20\n300,3,30,30\n",
        )

    def write_csv(self, filename, contents):
        (self.raw_dir / filename).write_text(contents, encoding="utf-8")

    def run_extraction(self, *, cities=("Bergamo", "Heidelberg"), include_trips=True):
        with patch.multiple(
            extract_cities,
            RAW_DIR=self.raw_dir,
            OUTPUT_DIR=self.output_dir,
            CITIES=cities,
            INCLUDE_TRIPS=include_trips,
        ):
            extract_cities.main()

    def read_rows(self, city, filename):
        path = self.output_dir / city / filename
        with duckdb.connect() as connection:
            return connection.read_parquet(str(path)).order("1, 2").fetchall()

    def test_project_root_resolves_from_new_script_location(self):
        self.assertEqual(
            extract_cities.PROJECT_ROOT, Path(__file__).resolve().parents[1]
        )

    def test_extracts_only_rows_belonging_to_each_requested_city(self):
        self.run_extraction()

        self.assertEqual(self.read_rows("bergamo", "cities.parquet"), [(1, "Bergamo")])
        self.assertEqual(
            self.read_rows("bergamo", "stations.parquet"),
            [(10, 1, "North"), (11, 1, "South")],
        )
        self.assertEqual(
            self.read_rows("bergamo", "station_status.parquet"),
            [(10, 1735689600, 5), (10, 1735693200, 2), (11, 1735689600, 3)],
        )
        self.assertEqual(self.read_rows("bergamo", "trips.parquet"), [(100, 1, 10, 11)])

        self.assertEqual(
            self.read_rows("heidelberg", "cities.parquet"), [(2, "Heidelberg")]
        )
        self.assertEqual(
            self.read_rows("heidelberg", "stations.parquet"), [(20, 2, "Center")]
        )
        self.assertEqual(
            self.read_rows("heidelberg", "station_status.parquet"),
            [(20, 1735689600, 1)],
        )
        self.assertEqual(
            self.read_rows("heidelberg", "trips.parquet"), [(200, 2, 20, 20)]
        )
        self.assertFalse((self.output_dir / "other_city").exists())

    def test_skips_unknown_city_and_matches_names_case_insensitively(self):
        self.run_extraction(cities=("Unknown", "bErGaMo"))

        self.assertFalse((self.output_dir / "unknown").exists())
        self.assertEqual(self.read_rows("bergamo", "cities.parquet"), [(1, "Bergamo")])

    def test_trips_csv_is_optional_when_trip_extraction_is_disabled(self):
        (self.raw_dir / "trips.csv").unlink()

        self.run_extraction(cities=("Bergamo",), include_trips=False)

        self.assertTrue(
            (self.output_dir / "bergamo" / "station_status.parquet").is_file()
        )
        self.assertFalse((self.output_dir / "bergamo" / "trips.parquet").exists())

    def test_missing_required_csv_fails_before_creating_city_output(self):
        for filename in (
            "cities.csv",
            "stations.csv",
            "station_status.csv",
            "trips.csv",
        ):
            with self.subTest(filename=filename):
                csv_path = self.raw_dir / filename
                original = csv_path.read_bytes()
                csv_path.unlink()
                try:
                    with self.assertRaisesRegex(
                        FileNotFoundError, f"Missing {filename}"
                    ):
                        self.run_extraction()
                    self.assertEqual(list(self.output_dir.iterdir()), [self.raw_dir])
                finally:
                    csv_path.write_bytes(original)
