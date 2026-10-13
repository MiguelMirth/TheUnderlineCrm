import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import {
  type CrmStatus,
  type DecisionResult,
  type EventOut,
  type Estimate,
  type Health,
  LIVE_STATUSES,
  type LeadAction,
  type LeadOut,
  type Preset,
  type PresetSettings,
  type PushResult,
  type RunCreate,
  type RunOut,
} from "./types";

const LIVE_POLL_MS = 2000;
const PRESET_ID = "underline";

export const keys = {
  presets: ["presets"] as const,
  presetSettings: ["preset-settings"] as const,
  health: ["health"] as const,
  estimate: (body: RunCreate) => ["estimate", body] as const,
  crm: ["crm"] as const,
  runs: ["runs"] as const,
  run: (id: string) => ["run", id] as const,
  events: (id: string) => ["events", id] as const,
  leads: (id: string) => ["leads", id] as const,
};

export function useCrmStatus() {
  return useQuery({
    queryKey: keys.crm,
    queryFn: () => api.get<CrmStatus>(`/api/crm/status?preset_id=${PRESET_ID}`),
    refetchInterval: 60_000,
  });
}

export function useRefreshCrm() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<CrmStatus>(`/api/crm/refresh?preset_id=${PRESET_ID}`),
    onSuccess: (status) => client.setQueryData(keys.crm, status),
  });
}

export function useDecide(runId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { action: LeadAction; lead_ids: string[] }) =>
      api.post<DecisionResult>(`/api/runs/${encodeURIComponent(runId)}/leads/decide`, body),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: keys.leads(runId) });
      client.invalidateQueries({ queryKey: keys.run(runId) });
    },
  });
}

export function usePresets() {
  return useQuery({ queryKey: keys.presets, queryFn: () => api.get<Preset[]>("/api/presets"), staleTime: Infinity });
}

export function usePresetSettings() {
  return useQuery({
    queryKey: keys.presetSettings,
    queryFn: () => api.get<PresetSettings>(`/api/presets/${PRESET_ID}/settings`),
    staleTime: Infinity,
  });
}

export function useSavePresetSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: PresetSettings) => api.put<PresetSettings>(`/api/presets/${PRESET_ID}/settings`, body),
    onSuccess: (settings) => {
      client.setQueryData(keys.presetSettings, settings);
      client.invalidateQueries({ queryKey: keys.presets });
    },
  });
}

export function useResetPresetSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<PresetSettings>(`/api/presets/${PRESET_ID}/settings/reset`),
    onSuccess: (settings) => {
      client.setQueryData(keys.presetSettings, settings);
      client.invalidateQueries({ queryKey: keys.presets });
    },
  });
}

export function useDeleteRun() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => api.delete(`/api/runs/${encodeURIComponent(runId)}`),
    onSuccess: (_data, runId) => {
      client.removeQueries({ queryKey: keys.run(runId) });
      client.invalidateQueries({ queryKey: keys.runs });
    },
  });
}

export function useHealth() {
  return useQuery({ queryKey: keys.health, queryFn: () => api.get<Health>("/api/health"), refetchInterval: 15000 });
}

export function useProbeEstimate() {
  return useMutation({
    mutationFn: (body: RunCreate) => api.post<Estimate>("/api/estimate?probe=true", body),
  });
}

export function useEstimate(body: RunCreate | null) {
  return useQuery({
    queryKey: body ? keys.estimate(body) : ["estimate", "none"],
    queryFn: () => api.post<Estimate>("/api/estimate", body),
    enabled: body !== null,
    placeholderData: (previous) => previous,
  });
}

export function useRuns() {
  return useQuery({
    queryKey: keys.runs,
    queryFn: () => api.get<RunOut[]>("/api/runs?limit=30"),
    refetchInterval: LIVE_POLL_MS,
  });
}

export function useRun(runId: string) {
  return useQuery({
    queryKey: keys.run(runId),
    queryFn: () => api.get<RunOut>(`/api/runs/${encodeURIComponent(runId)}`),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && LIVE_STATUSES.includes(status) ? LIVE_POLL_MS : false;
    },
  });
}

export function useRunEvents(runId: string) {
  return useQuery({
    queryKey: keys.events(runId),
    queryFn: () => api.get<EventOut[]>(`/api/runs/${encodeURIComponent(runId)}/events?limit=300`),
    refetchInterval: LIVE_POLL_MS,
  });
}

// All leads for the run. The Review screen filters the tabs locally.
export function useLeads(runId: string) {
  return useQuery({
    queryKey: keys.leads(runId),
    queryFn: () => api.get<LeadOut[]>(`/api/runs/${encodeURIComponent(runId)}/leads`),
    refetchInterval: LIVE_POLL_MS,
  });
}

export function useStartRun() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: RunCreate) => api.post<RunOut>("/api/runs", body),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.runs }),
  });
}

export function usePush(runId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<PushResult>(`/api/runs/${encodeURIComponent(runId)}/push`, { lead_ids: [] }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: keys.leads(runId) });
      client.invalidateQueries({ queryKey: keys.run(runId) });
      client.invalidateQueries({ queryKey: keys.events(runId) });
    },
  });
}

export function useEnrich(runId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<RunOut>(`/api/runs/${encodeURIComponent(runId)}/enrich`),
    onSuccess: (run) => {
      client.setQueryData(keys.run(runId), run);
      client.invalidateQueries({ queryKey: keys.runs });
      client.invalidateQueries({ queryKey: keys.events(runId) });
    },
  });
}

export function useRunAction(runId: string, action: "resume" | "cancel") {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<RunOut>(`/api/runs/${encodeURIComponent(runId)}/${action}`),
    onSuccess: (run) => {
      client.setQueryData(keys.run(runId), run);
      client.invalidateQueries({ queryKey: keys.runs });
      client.invalidateQueries({ queryKey: keys.events(runId) });
    },
  });
}
