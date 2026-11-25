"use client";

import { useEffect, useRef, useState } from "react";
import type { PointerEvent } from "react";
import type { DemoData, Station, StationReading } from "@/types/station";
import { statusLabels } from "@/lib/snapshots";

type Point = { x: number; y: number };
type Size = { width: number; height: number };
type View = { center: Point; zoom: number };
const tileSize = 256;

function project(latitude: number, longitude: number): Point {
  return {
    x: (longitude + 180) / 360,
    y: (1 - Math.asinh(Math.tan(latitude * Math.PI / 180)) / Math.PI) / 2,
  };
}

function fit(points: Point[], { width, height }: Size): View {
  const xs = points.map(({ x }) => x);
  const ys = points.map(({ y }) => y);
  const left = Math.min(...xs), right = Math.max(...xs);
  const top = Math.min(...ys), bottom = Math.max(...ys);
  const scale = Math.min((width - 64) / (right - left), (height - 64) / (bottom - top));
  return {
    center: { x: (left + right) / 2, y: (top + bottom) / 2 },
    zoom: Math.max(10, Math.min(15, Math.floor(Math.log2(scale / tileSize)))),
  };
}

const neighborhoods = [
  ["Città Alta", 45.7069, 9.6634],
  ["Centro", 45.6977, 9.6700],
  ["Borgo Palazzo", 45.6968, 9.6966],
  ["Boccaleone", 45.6849, 9.6936],
  ["Malpensata", 45.6831, 9.6728],
  ["Papa Giovanni XXIII", 45.6865, 9.6378],
] as const;

export function StationMap({
  stations, serviceArea, states, selectedId, onSelect,
}: {
  stations: Station[];
  serviceArea: DemoData["serviceArea"];
  states: Record<string, StationReading>;
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  const area = serviceArea.coordinates.map((ring) =>
    ring.map(([longitude, latitude]) => project(latitude, longitude))
  );
  const markers = stations.map((station) => ({
    ...station, point: project(station.latitude, station.longitude),
  }));
  const bounds = [...area.flat(), ...markers.map(({ point }) => point)];
  const initialSize = { width: 800, height: 490 };
  const [size, setSize] = useState(initialSize);
  const [view, setView] = useState(() => fit(bounds, initialSize));
  const [streets, setStreets] = useState(false);
  const [tileError, setTileError] = useState(false);
  const mapRef = useRef<HTMLDivElement>(null);
  const hasMeasured = useRef(false);
  const drag = useRef<{ pointer: number; start: Point; view: View } | null>(null);

  useEffect(() => {
    const node = mapRef.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize({ width, height });
      if (!hasMeasured.current) {
        hasMeasured.current = true;
        const points = serviceArea.coordinates.flat().map(([longitude, latitude]) =>
          project(latitude, longitude)
        );
        points.push(...stations.map(({ latitude, longitude }) => project(latitude, longitude)));
        setView(fit(points, { width, height }));
      }
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [serviceArea, stations]);

  const world = tileSize * 2 ** view.zoom;
  const offset = { x: view.center.x * world - size.width / 2, y: view.center.y * world - size.height / 2 };
  const position = ({ x, y }: Point) => ({ x: x * world - offset.x, y: y * world - offset.y });
  const areaPath = area.map((ring) =>
    ring.map((point, index) => {
      const { x, y } = position(point);
      return `${index === 0 ? "M" : "L"} ${x} ${y}`;
    }).join(" ") + " Z"
  ).join(" ");

  const tiles = [];
  if (streets) {
    for (let x = Math.floor(offset.x / tileSize); x < Math.ceil((offset.x + size.width) / tileSize); x += 1) {
      for (let y = Math.floor(offset.y / tileSize); y < Math.ceil((offset.y + size.height) / tileSize); y += 1) {
        const edge = 2 ** view.zoom;
        if (x >= 0 && x < edge && y >= 0 && y < edge) tiles.push({ x, y });
      }
    }
  }

  function pan(dx: number, dy: number, current: View) {
    const scale = tileSize * 2 ** current.zoom;
    setView({
      ...current,
      center: {
        x: Math.max(0, Math.min(1, current.center.x + dx / scale)),
        y: Math.max(0, Math.min(1, current.center.y + dy / scale)),
      },
    });
  }

  function changeZoom(change: number) {
    setView((current) => ({ ...current, zoom: Math.min(17, Math.max(10, current.zoom + change)) }));
  }

  function startDrag(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || (event.target as Element).closest("button, a")) return;
    drag.current = { pointer: event.pointerId, start: { x: event.clientX, y: event.clientY }, view };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  return (
    <section className="map-panel" aria-label="Bergamo station map">
      <div className="map-header">
        <h2>Station map</h2>
        <button
          className="street-switch" type="button" aria-pressed={streets}
          onClick={() => { setTileError(false); setStreets(!streets); }}
        >Street layer (online)</button>
      </div>
      <div
        className="map-surface" ref={mapRef} role="group" aria-label="Station positions"
        tabIndex={0}
        onKeyDown={(event) => {
          if (event.currentTarget !== event.target) return;
          const directions: Record<string, [number, number]> = {
            ArrowUp: [0, -72], ArrowDown: [0, 72], ArrowLeft: [-72, 0], ArrowRight: [72, 0],
          };
          const direction = directions[event.key];
          if (direction) { event.preventDefault(); pan(...direction, view); }
          if (event.key === "+" || event.key === "-") changeZoom(event.key === "+" ? 1 : -1);
        }}
        onPointerDown={startDrag}
        onPointerMove={(event) => {
          const active = drag.current;
          if (active?.pointer === event.pointerId) {
            pan(active.start.x - event.clientX, active.start.y - event.clientY, active.view);
          }
        }}
        onLostPointerCapture={() => { drag.current = null; }}
        onPointerUp={() => { drag.current = null; }}
        onPointerCancel={() => { drag.current = null; }}
      >
        {tiles.map(({ x, y }) => (
          // Street tiles are placed in projected map coordinates.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            alt="" key={`${view.zoom}/${x}/${y}`} className="map-tile" draggable={false}
            width={tileSize} height={tileSize}
            style={{ left: x * tileSize - offset.x, top: y * tileSize - offset.y }}
            src={`https://tile.openstreetmap.org/${view.zoom}/${x}/${y}.png`}
            onError={() => setTileError(true)}
          />
        ))}
        <svg className={`coverage ${streets ? "with-streets" : ""}`} width="100%" height="100%" aria-hidden="true">
          <path d={areaPath} fillRule="evenodd" />
        </svg>
        {!streets && neighborhoods.map(([name, lat, lon]) => {
          const { x, y } = position(project(lat, lon));
          return <span key={name} className="neighborhood" style={{ left: x, top: y }}>{name}</span>;
        })}
        {markers.map(({ id, name, point }) => {
          const { x, y } = position(point);
          const status = states[id].status;
          const selected = id === selectedId;
          return (
            <button
              key={id} type="button" onClick={() => onSelect(id)} style={{ left: x, top: y }}
              aria-label={`${name}. ${statusLabels[status]}`} aria-pressed={selected}
              className={`marker ${status}${selected ? " selected" : ""}`}
              title={name}
            ><span /></button>
          );
        })}
        <div className="zoom-controls" role="group" aria-label="Map controls">
          <button type="button" aria-label="Zoom in" onClick={() => changeZoom(1)} disabled={view.zoom === 17}>+</button>
          <button type="button" aria-label="Zoom out" onClick={() => changeZoom(-1)} disabled={view.zoom === 10}>−</button>
          <button type="button" onClick={() => setView(fit(bounds, size))}>Fit</button>
        </div>
        {tileError && <p className="map-note" role="status">Some street tiles are unavailable.</p>}
        <div className="map-credit">
          {streets
            ? <a href="https://www.openstreetmap.org/copyright">© OpenStreetMap contributors</a>
            : "Historical service area"}
        </div>
      </div>
    </section>
  );
}
