import type { ToggleSpec } from "../api/types";

const WHAT: Record<string, string> = {
  florida_person_only: "Only a person in Florida can pass.",
  require_us: "The person must be in the United States.",
  allow_global_org: "A company based outside the US can still pass.",
  min_confidence: "Lowest confidence a brand can have and still pass.",
  min_brand_revenue: "Minimum company revenue, in US dollars.",
  min_employees: "Minimum number of employees. Zero means no floor.",
  max_per_company: "How many people to keep from one company. Zero means no cap.",
  min_contact_score: "Lowest score a person can have and still pass.",
  discover_new_events: "Looks for events that are not in the seed. This spends credits.",
  max_tier: "3 searches Florida. 4 searches the United States.",
  require_spend_evidence: "Requires a record of paid sponsorship before the lead can pass.",
  min_revenue: "Minimum company revenue, in US dollars.",
  org_path: "Also searches companies by keyword. Each results page costs one Apollo credit.",
  us_fallback: "Turns off the Florida limit and searches the United States.",
};

function defaultText(spec: ToggleSpec): string {
  if (spec.kind === "bool") return spec.default ? "Default on." : "Default off.";
  if (spec.kind === "int") return `Default ${Number(spec.default).toLocaleString("en-US")}.`;
  return `Default ${String(spec.default)}.`;
}

export function gateHint(spec: ToggleSpec): string {
  const what = WHAT[spec.id];
  const fallback = spec.label.replace(/^[^()]+\(([^)]+)\)\s*$/, "$1");
  const sentence = what ?? (fallback !== spec.label ? fallback : "");
  return [sentence, defaultText(spec)].filter(Boolean).join(" ");
}

export function gateLabel(spec: ToggleSpec): string {
  return spec.label.replace(/\s*\([^)]*\)\s*$/, "");
}
