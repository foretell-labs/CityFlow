"use client";

import { useState } from "react";
import type { DemoData, StationStatus } from "@/types/station";
import { formatDate, formatTime, statusLabels } from "@/lib/snapshots";
import { StationMap } from "@/components/StationMap";

export function StationDashboard({ data }: { data: DemoData }) {
  const { stations, snapshots, serviceArea } = data;
  const [snapshotIndex, setSnapshotIndex] = useState(snapshots.length - 1);
  const [stationId, setStationId] = useState(() => {
    const states = snapshots[snapshots.length - 1].states;
    return stations.find((station) => states[station.id].status === "shortage")?.id
      ?? stations[0].id;
  });
  const snapshot = snapshots[snapshotIndex];
  const station = stations.find(({ id }) => id === stationId) ?? stations[0];
  const reading = snapshot.states[station.id];
  const counts = { available: 0, shortage: 0, unavailable: 0 };
  for (const state of Object.values(snapshot.states)) {
    counts[state.status] += 1;
  }
  const statuses: StationStatus[] = ["available", "shortage", "unavailable"];

  return (
    <main className="page-shell">
      <div className="masthead">
        <span className="wordmark"><span className="brand-mark" aria-hidden="true" />CityFlow</span>
        <span className="replay-label">Historical replay</span>
      </div>

      <header className="page-heading">
        <div>
          <h1>Bergamo</h1>
          <p>Two-hour bike-share outlook</p>
        </div>
        <div className="snapshot-control">
          <span className="snapshot-label">{formatDate(snapshot.issueTime)} · Bergamo time</span>
          <div className="snapshot-options" role="group" aria-label="Forecast issue time">
            {snapshots.map((entry, index) => (
              <button
                key={entry.issueTime}
                type="button"
                aria-pressed={index === snapshotIndex}
                onClick={() => setSnapshotIndex(index)}
              >
                {formatTime(entry.issueTime)}
              </button>
            ))}
          </div>
        </div>
      </header>

      <div className="outlook-strip" aria-live="polite">
        <div><strong>{formatTime(snapshot.targetTime)}</strong><span>Forecast target</span></div>
        {statuses.map((status) => (
          <div key={status}>
            <strong><i className={`status-dot ${status}`} />{counts[status]}</strong>
            <span>{statusLabels[status]}</span>
          </div>
        ))}
      </div>

      <div className="dashboard-grid">
        <StationMap
          stations={stations}
          serviceArea={serviceArea}
          states={snapshot.states}
          selectedId={stationId}
          onSelect={setStationId}
        />
        <section className="station-panel" aria-label="Selected station">
          <label className="station-picker">
            Station
            <select value={stationId} onChange={(event) => setStationId(event.target.value)}>
              {stations.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
          </label>

          <div className="station-reading" aria-live="polite">
            <h2>{station.name}</h2>
            <div className="bike-reading">
              <strong>{reading.bikes ?? "—"}</strong>
              <span>Rentable bikes recorded<br />as of {formatTime(snapshot.issueTime)}</span>
            </div>
            <dl>
              <div>
                <dt>Forecast for {formatTime(snapshot.targetTime)}</dt>
                <dd><i className={`status-dot ${reading.status}`} />{statusLabels[reading.status]}</dd>
              </div>
              <div>
                <dt>Last recorded update</dt>
                <dd>{reading.updatedAt ? `${formatDate(reading.updatedAt)} · ${formatTime(reading.updatedAt)}` : "Unavailable"}</dd>
              </div>
            </dl>
            {reading.reason && <p className="unavailable-note">{reading.reason}</p>}
          </div>
          <p className="method-note">The persistence baseline carries the selected reading forward by two hours.</p>
        </section>
      </div>

      <footer className="source-note">
        <a href="https://github.com/TUMFTM/european-bike-sharing-dataset">European Bike-Sharing Dataset</a>
        <span>·</span><span>CC BY-NC 4.0</span>
      </footer>
    </main>
  );
}
