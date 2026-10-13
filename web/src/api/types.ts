// Named aliases over the generated schema. Import from here, not from schema.ts.
import type { components } from "./schema";

type Schemas = components["schemas"];

export type Preset = Schemas["Preset"];
export type PresetSettings = Schemas["PresetSettings"];
export type VerticalSettings = Schemas["VerticalSettings"];
export type PersonTier = Schemas["PersonTier"];
export type ToggleDefault = Schemas["ToggleDefault"];
export type VerticalSpec = Schemas["VerticalSpec"];
export type ToggleSpec = Schemas["ToggleSpec"];
export type ToggleState = Schemas["ToggleState"];
export type Caps = Schemas["Caps"];
export type Estimate = Schemas["Estimate"];
export type ProviderEstimate = Schemas["ProviderEstimate"];
export type SpendLine = Schemas["SpendLine"];
export type RunCreate = Schemas["RunCreate"];
export type RunOut = Schemas["RunOut"];
export type RunStatus = RunOut["status"];
export type LeadOut = Schemas["LeadOut"];
export type LeadState = LeadOut["state"];
export type GateStep = Schemas["GateStep"];
export type EventOut = Schemas["EventOut"];
export type Health = Schemas["Health"];
export type CrmStatus = Schemas["CrmStatus"];
export type DecisionResult = Schemas["DecisionResult"];
export type RefusedLead = Schemas["RefusedLead"];
export type PushResult = Schemas["PushResult"];
export type PushRow = Schemas["PushRow"];
export type LeadAction = Schemas["LeadBulkAction"]["action"];

export type ToggleValue = boolean | number | string;

// Statuses where the worker is (or will be) doing work. The Review screen polls these.
export const LIVE_STATUSES: RunStatus[] = ["queued", "running", "enriching"];
// Statuses an operator can resume from (plan section 4).
export const RESUMABLE_STATUSES: RunStatus[] = ["interrupted", "budget_stopped", "error"];
