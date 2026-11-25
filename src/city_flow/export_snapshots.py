"""Export three historical Bergamo snapshots for the standalone demo."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

BERGAMO_TIME = ZoneInfo("Europe/Rome")
ISSUE_HOURS = (8, 12, 17)
MAX_READING_AGE_SECONDS = 6 * 3600
HORIZON_SECONDS = 2 * 3600


def iso_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, UTC).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city-dir", type=Path, required=True)
    parser.add_argument("--city-areas", type=Path)
    args = parser.parse_args()
    city_dir = args.city_dir
    city_areas = args.city_areas or city_dir.parent / "raw" / "city_areas.csv"
    issues = [
        int(datetime(2023, 4, 18, hour, tzinfo=BERGAMO_TIME).timestamp())
        for hour in ISSUE_HOURS
    ]
    snapshots = {
        issue: {
            "issueTime": iso_time(issue),
            "targetTime": iso_time(issue + HORIZON_SECONDS),
            "states": {},
        }
        for issue in issues
    }
    with duckdb.connect() as con:
        # pyrefly: ignore[not-iterable]
        city_name, area_json = con.execute(
            """
            SELECT c.name, a.geom_geojson
            FROM read_csv_auto(?) a
            JOIN read_parquet(?) c ON a.city_id = c.id
            """,
            [str(city_areas), str(city_dir / "cities.parquet")],
        ).fetchone()
        if city_name != "Bergamo":
            raise ValueError(f"The Bergamo demo requires Bergamo data, got {city_name}")
        records = con.execute(
            """
            WITH grid AS (
                SELECT st.id, st.name, st.lat, st.lon, t.issue_time
                FROM read_parquet(?) st
                CROSS JOIN UNNEST(?::BIGINT[]) t(issue_time)
                WHERE st.id IS NOT NULL AND isfinite(st.lat) AND isfinite(st.lon)
            )
            SELECT g.*, s.time, s.bikes_available_to_rent, s.maintenance
            FROM grid g
            ASOF LEFT JOIN read_parquet(?) s
              ON s.station_id = g.id AND s.time <= g.issue_time
            ORDER BY g.issue_time, g.name, g.id
            """,
            [
                str(city_dir / "stations.parquet"),
                issues,
                str(city_dir / "station_status.parquet"),
            ],
        ).fetchall()
    stations = {}
    for station_id, name, lat, lon, issue, updated, bikes, maintenance in records:
        key = str(station_id)
        states = snapshots[issue]["states"]
        if key in states:
            raise ValueError(f"Duplicate station {station_id} at {iso_time(issue)}")

        stations[key] = {"id": key, "name": name, "latitude": lat, "longitude": lon}
        if maintenance:
            reason = "Station under maintenance"
        elif updated is None or bikes is None or bikes < 0:
            reason = "Rentable-bike count unavailable"
        elif issue - updated > MAX_READING_AGE_SECONDS:
            reason = "Last recorded update is over six hours old"
        else:
            reason = None

        states[key] = {
            "status": "unavailable"
            if reason
            else "shortage"
            if bikes <= 2
            else "available",
            "bikes": bikes if bikes is not None and bikes >= 0 else None,
            "updatedAt": iso_time(updated) if updated is not None else None,
            "reason": reason,
        }

    if not stations or any(
        len(s["states"]) != len(stations) for s in snapshots.values()
    ):
        raise ValueError("Each snapshot must include every mapped station")
    output = (
        Path(__file__).resolve().parents[1] / "frontend" / "data" / "snapshots.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "stations": list(stations.values()),
                "snapshots": list(snapshots.values()),
                "serviceArea": json.loads(area_json),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Exported {len(stations)} stations across {len(snapshots)} snapshots.")


if __name__ == "__main__":
    main()
