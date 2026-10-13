import * as Tabs from "@radix-ui/react-tabs";
import { useMemo, useState } from "react";
import { useDeleteRun, useEstimate, usePresets, useProbeEstimate, useRuns, useStartRun } from "../api/queries";
import { ApiError } from "../api/client";
import { LIVE_STATUSES, type Estimate as EstimateData, type Preset, type RunCreate, type ToggleValue, type VerticalSpec, type RunOut } from "../api/types";
import { CrmStrip } from "../components/CrmStrip";
import { Estimate } from "../components/Estimate";
import { NumberField } from "../components/NumberField";
import { PrimaryAction } from "../components/PrimaryAction";
import { ToggleList } from "../components/ToggleList";
import { fmtTime, statusLabel } from "../lib/format";
import { CAP_LABELS, RUN_CAP_KEYS } from "../lib/caps";
import { navigate } from "../lib/router";
import { Hint } from "../components/Hint";
import { TrashButton } from "../components/TrashButton";

export function Gather() {
  const presets = usePresets();
  const runs = useRuns();
  const [presetId, setPresetId] = useState<string | null>(null);
  const [verticalId, setVerticalId] = useState<string | null>(null);

  if (presets.isPending) return <p className="py-16 text-[15px] text-ink-soft">Loading presets</p>;
  if (presets.isError) {
    return <p className="py-16 text-[15px] text-alarm">Could not load presets. {String(presets.error)}</p>;
  }

  const available = presets.data;
  const preset = available.find((p) => p.id === presetId) ?? available[0];
  if (!preset) return <p className="py-16 text-[15px] text-ink-soft">No presets are registered.</p>;
  const vertical = preset.verticals.find((v) => v.id === verticalId) ?? preset.verticals[0];

  return (
    <div className="pt-6 sm:pt-8">
      <header className="max-w-2xl">
        <p className="text-[13px] text-ink-soft">New run</p>
        <h1 className="mt-2 font-serif text-[3rem] leading-[0.95] tracking-[-0.02em] sm:text-[3.5rem]">{preset.name}</h1>
        <p className="mt-3 text-[15px] text-ink-soft">
          {preset.place} · {preset.year}
        </p>
        {available.length > 1 ? (
          <label className="mt-5 block max-w-xs text-[14px]">
            <span className="text-[13px] text-ink-soft">Preset</span>
            <select
              value={preset.id}
              onChange={(event) => setPresetId(event.target.value)}
              className="field mt-1"
            >
              {available.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}, {p.place} {p.year}
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </header>

      <Tabs.Root value={vertical.id} onValueChange={setVerticalId} className="mt-10">
        <Tabs.List className="flex flex-wrap gap-x-8 gap-y-2 border-b border-line" aria-label="Verticals">
          {preset.verticals.map((v) => (
            <Tabs.Trigger
              key={v.id}
              value={v.id}
              className="-mb-px border-b-2 border-transparent pb-3 font-serif text-[1.35rem] leading-none text-ink-soft data-[state=active]:border-ink data-[state=active]:text-ink"
            >
              {v.label}
            </Tabs.Trigger>
          ))}
        </Tabs.List>
      </Tabs.Root>

      <div className="mt-8 grid gap-10 border-b border-line pb-8 lg:grid-cols-2">
        <CrmStrip liveRunId={runs.data?.find((r) => LIVE_STATUSES.includes(r.status))?.id ?? null} />
        <section>
          <h2 className="font-serif text-[1.75rem] leading-none tracking-[-0.02em]">Recent runs</h2>
          <RecentRuns runs={runs.data} loading={runs.isPending} error={runs.isError} />
        </section>
      </div>

      <VerticalPanel key={`${preset.id}:${vertical.id}`} preset={preset} vertical={vertical} />
    </div>
  );
}

function VerticalPanel({ preset, vertical }: { preset: Preset; vertical: VerticalSpec }) {
  const defaults = useMemo(() => {
    const toggles: Record<string, ToggleValue> = {};
    for (const t of vertical.toggles) toggles[t.id] = t.default;
    const caps: Record<string, number> = {};
    for (const [key, value] of Object.entries(vertical.caps as Record<string, number>)) {
      if (RUN_CAP_KEYS.has(key) && CAP_LABELS[key] && value > 0) caps[key] = value;
    }
    return { toggles, caps };
  }, [vertical]);

  const [toggles, setToggles] = useState<Record<string, ToggleValue>>(defaults.toggles);
  const [caps, setCaps] = useState<Record<string, number>>(defaults.caps);
  const [startError, setStartError] = useState<string | null>(null);
  const [measured, setMeasured] = useState<{ key: string; estimate: EstimateData } | null>(null);

  const body: RunCreate = useMemo(
    () => ({ preset_id: preset.id, vertical_id: vertical.id, toggles, caps, brief: "" }),
    [preset.id, vertical.id, toggles, caps],
  );
  const bodyKey = JSON.stringify(body);
  const estimate = useEstimate(body);
  const probe = useProbeEstimate();
  const start = useStartRun();
  const peopleLane = vertical.source.kind === "apollo_people";

  const estimateData = measured?.key === bodyKey ? measured.estimate : estimate.data;
  const canStart = Boolean(estimateData?.can_start) && !estimate.isFetching && !probe.isPending;
  let reason: string | null = null;
  if (startError) reason = startError;
  else if (estimateData && !estimateData.can_start) reason = estimateData.blockers.join(" ");

  const estimateError = probe.isError
    ? errorText(probe.error)
    : estimate.isError
      ? errorText(estimate.error)
      : undefined;

  return (
    <div className="mt-8">
      <p className="roboto max-w-xl text-[16px] leading-relaxed">{vertical.icp}</p>
      <div className="mt-10 grid items-start gap-x-16 gap-y-12 lg:grid-cols-[minmax(0,1fr)_21.5rem]">
      <div className="order-2 min-w-0 lg:order-1">
        {Object.keys(caps).length > 0 ? (
          <section>
            <h2 className="font-serif text-[1.75rem] leading-none tracking-[-0.02em]">Limits</h2>
            <div className="mt-4 border-y border-line">
              {Object.entries(caps).map(([key, value]) => (
                <label
                  key={key}
                  className="grid grid-cols-[minmax(0,1fr)_9rem] items-center gap-6 border-b border-line py-3.5 last:border-b-0"
                >
                  <span className="text-[15px]">{CAP_LABELS[key]}</span>
                  <NumberField
                    label={CAP_LABELS[key]}
                    value={value}
                    onChange={(next) => setCaps((prev) => ({ ...prev, [key]: next }))}
                  />
                </label>
              ))}
            </div>
          </section>
        ) : null}

        <section className={Object.keys(caps).length > 0 ? "mt-10" : undefined}>
          <h2 className="font-serif text-[1.75rem] leading-none tracking-[-0.02em]">Gates</h2>
          <div className="mt-4">
            <ToggleList
              toggles={vertical.toggles}
              values={toggles}
              onChange={(id, value) => {
                setStartError(null);
                setToggles((prev) => ({ ...prev, [id]: value }));
              }}
            />
          </div>
        </section>
      </div>

      <aside className="order-1 min-w-0 lg:sticky lg:top-[4.75rem] lg:order-2">
        <div className="border border-ink">
          <div className="p-5 sm:p-6">
            <h2 className="font-serif text-[1.75rem] leading-none tracking-[-0.02em]">Estimate</h2>
            <div className="mt-4">
              <Estimate
                estimate={estimateData}
                loading={estimate.isFetching || probe.isPending}
                error={estimateError}
              />
            </div>
          </div>
          <div className="border-t border-line p-5 sm:p-6">
            {peopleLane ? (
              <>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    disabled={probe.isPending}
                    onClick={() => {
                      setStartError(null);
                      probe.mutate(body, {
                        onSuccess: (next) => setMeasured({ key: bodyKey, estimate: next }),
                      });
                    }}
                    className="btn btn-line min-w-0 flex-1"
                  >
                    {probe.isPending ? "Measuring…" : "Measure free probe"}
                  </button>
                  <Hint text="Searches Apollo people at no credit cost, then replaces the upper bounds. Large page caps can take a few minutes." />
                </div>
              </>
            ) : null}
            <div className={peopleLane ? "mt-4" : undefined}>
              <PrimaryAction
                full
                label="Start run"
                disabled={!canStart}
                busy={start.isPending}
                reason={reason}
                tone={startError ? "alarm" : "neutral"}
                onClick={() => {
                  setStartError(null);
                  start.mutate(body, {
                    onSuccess: (run: RunOut) => navigate(`/runs/${run.id}`),
                    onError: (error) => setStartError(errorText(error)),
                  });
                }}
              />
            </div>
          </div>
        </div>
      </aside>
      </div>
    </div>
  );
}

function RecentRuns({ runs, loading, error }: { runs?: RunOut[]; loading: boolean; error: boolean }) {
  const remove = useDeleteRun();
  const [armed, setArmed] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  if (loading) return <p className="mt-4 text-[14px] text-ink-soft">Loading runs</p>;
  if (error) return <p className="mt-4 text-[14px] text-alarm">Could not load runs.</p>;
  if (!runs || runs.length === 0) {
    return <p className="mt-4 text-[14px] text-ink-soft">No runs yet.</p>;
  }
  return (
    <>
      {deleteError ? <p className="mt-4 text-[14px] text-alarm">{deleteError}</p> : null}
      <ul className="mt-4 border-t border-line">
        {runs.map((run) => {
          const live = LIVE_STATUSES.includes(run.status);
          return (
            <li key={run.id} className="flex items-center border-b border-line">
              <a
                href={`/runs/${run.id}`}
                onClick={(event) => {
                  event.preventDefault();
                  navigate(`/runs/${run.id}`);
                }}
                className="min-w-0 flex-1 py-3.5 pr-2 hover:bg-paper-sunk"
              >
                <span className="flex items-baseline justify-between gap-3">
                  <span className="font-serif text-[1.2rem] leading-none">{run.vertical_label}</span>
                  <span className="text-[12px] text-ink-soft tabular-nums">{run.id}</span>
                </span>
                <span className="mt-1.5 block text-[13px] text-ink-soft">
                  <span className="roboto text-ink">{statusLabel(run.status)}</span>
                  {" · "}
                  {fmtTime(run.created_at)}
                  {" · "}
                  {run.started_by}
                </span>
              </a>
              <TrashButton
                armed={armed === run.id}
                disabled={live || remove.isPending}
                onClick={() => {
                  setDeleteError(null);
                  if (live) return;
                  if (armed !== run.id) {
                    setArmed(run.id);
                    return;
                  }
                  remove.mutate(run.id, {
                    onSuccess: () => setArmed(null),
                    onError: (err) => setDeleteError(errorText(err)),
                  });
                }}
              />
            </li>
          );
        })}
      </ul>
    </>
  );
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Unknown error";
}
