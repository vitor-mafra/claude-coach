import type { RestSpec, RunSegment, Weekday } from "./api";

const WEEKDAY_LABEL: Record<Weekday, string> = {
  mon: "Seg",
  tue: "Ter",
  wed: "Qua",
  thu: "Qui",
  fri: "Sex",
  sat: "Sáb",
  sun: "Dom",
};

export const weekdayLabel = (w: Weekday): string => WEEKDAY_LABEL[w];

export const orderedWeekdays: Weekday[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

export function formatRest(r: RestSpec | null | undefined): string {
  if (!r) return "";
  if (r.seconds != null) return `${r.seconds}s`;
  if (r.min_seconds != null && r.max_seconds != null) return `${r.min_seconds}-${r.max_seconds}s`;
  if (r.min_seconds != null) return `≥${r.min_seconds}s`;
  if (r.max_seconds != null) return `≤${r.max_seconds}s`;
  return r.note ?? "";
}

export function formatSegment(s: RunSegment): string {
  const amount = s.distance_km != null
    ? `${s.distance_km}km`
    : s.duration_min != null
    ? `${s.duration_min}min`
    : "?";
  const prefix = s.repeats > 1 ? `${s.repeats}×` : "";
  const tag = s.note ? ` (${s.note})` : "";
  return `${prefix}${amount} @ ${s.hr_zone}${tag}`;
}
