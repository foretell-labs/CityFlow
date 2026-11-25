import type { StationStatus } from "@/types/station";

export const statusLabels: Record<StationStatus, string> = {
  available: "3+ bikes predicted",
  shortage: "0–2 bikes predicted",
  unavailable: "Forecast unavailable",
};

const clock = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Rome",
});

const date = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "long",
  year: "numeric",
  timeZone: "Europe/Rome",
});

export function formatTime(iso: string): string {
  return clock.format(new Date(iso));
}

export function formatDate(iso: string): string {
  return date.format(new Date(iso));
}
