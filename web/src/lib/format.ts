import type { ToggleSpec, ToggleValue } from "../api/types";

export type ToggleStatus = "default" | "relaxed" | "tightened" | "changed";

// Mirrors ToggleSpec.status_for in src/engine/models.py. The server stays the authority at Start;
// this copy only labels the form while the operator types.
export function toggleStatus(spec: ToggleSpec, value: ToggleValue): ToggleStatus {
  if (value === spec.default) return "default";
  if (spec.relaxed_when == null) return "changed";
  if (spec.kind === "bool") return value === (spec.relaxed_when === "on") ? "relaxed" : "tightened";
  if (spec.kind === "int") {
    const n = Number(value);
    const d = Number(spec.default);
    if (spec.relaxed_when === "lower") return n < d ? "relaxed" : "tightened";
    return n > d ? "relaxed" : "tightened";
  }
  return value === spec.relaxed_when ? "relaxed" : "tightened";
}

export function fmtNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "n/a";
  return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

export function fmtTime(iso: string): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("en-US", {
    timeZone: "America/New_York",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

export function statusLabel(status: string): string {
  const words = status.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
