export type StationStatus = "available" | "shortage" | "unavailable";

export type Station = {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
};

export type StationReading = {
  status: StationStatus;
  bikes: number | null;
  updatedAt: string | null;
  reason: string | null;
};

export type Snapshot = {
  issueTime: string;
  targetTime: string;
  states: Record<string, StationReading>;
};

export type DemoData = {
  stations: Station[];
  snapshots: Snapshot[];
  serviceArea: { type: "Polygon"; coordinates: number[][][] };
};
