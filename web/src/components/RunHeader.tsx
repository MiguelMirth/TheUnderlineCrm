import type { RunOut } from "../api/types";
import { LIVE_STATUSES, RESUMABLE_STATUSES } from "../api/types";
import { fmtNumber, fmtTime, statusLabel } from "../lib/format";
import { PrimaryAction } from "./PrimaryAction";
import { TrashButton } from "./TrashButton";

const CANCELLABLE = [
  "queued",
  "running",
  "awaiting_enrich",
  "enriching",
  "interrupted",
  "budget_stopped",
  "error",
];

const PROVIDER_NAME: Record<string, string> = { apollo: "Apollo", tavily: "Tavily", cursor: "Cursor", gemini: "Gemini" };

export function RunHeader({
  run,
  onResume,
  onCancel,
  onEnrich,
  onPush,
  onDelete,
  enrichArmed,
  deleteArmed,
  pushCount,
  pending,
  actionError,
}: {
  run: RunOut;
  onResume: () => void;
  onCancel: () => void;
  onEnrich: () => void;
  onPush: () => void;
  onDelete: () => void;
  enrichArmed: boolean;
  deleteArmed: boolean;
  pushCount: number;
  pending: boolean;
  actionError?: string;
}) {
  const resumable = RESUMABLE_STATUSES.includes(run.status);
  const shortlisted = run.counts.shortlisted ?? 0;
  const enrichLater = (run.status === "needs_review" || run.status === "complete") && shortlisted > 0;
  const awaitingEnrich = run.status === "awaiting_enrich" || enrichLater;
  const showPush = pushCount > 0 && !["queued", "running", "enriching", "awaiting_enrich"].includes(run.status);
  const cancellable = CANCELLABLE.includes(run.status);
  const live = LIVE_STATUSES.includes(run.status);
  const providers = Array.from(new Set([...Object.keys(run.reservation), ...Object.keys(run.spend)]));
  const hasAction = showPush || awaitingEnrich || resumable || cancellable;

  return (
    <section>
      <div className="flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-1">
            <p className="text-[13px] text-ink-soft">Run {run.id}</p>
            <TrashButton armed={deleteArmed} disabled={pending || live} onClick={onDelete} />
          </div>
          <h1 className="mt-2 font-serif text-[2.75rem] leading-[0.95] tracking-[-0.02em] sm:text-[3.25rem]">
            {run.vertical_label}
          </h1>
          <p className="mt-4 text-[17px] leading-snug">
            <span className="roboto">{statusLabel(run.status)}</span>
            {run.stage_name ? <span className="text-ink-soft"> · {run.stage_name}</span> : null}
          </p>
          <p className="mt-1 text-[14px] text-ink-soft">
            Started {fmtTime(run.created_at)} by {run.started_by}
          </p>
          {run.status === "running" || run.status === "queued" ? (
            <p className="mt-1 text-[13px] text-ink-soft">Refreshes every 2 seconds while the run is live.</p>
          ) : null}
        </div>

        {hasAction ? (
        <div className="w-full shrink-0 sm:max-w-xs">
            {showPush ? (
              <PrimaryAction
                full
                label={`Push ${pushCount}`}
                onClick={onPush}
                busy={pending}
                reason="You confirm once. That writes the approved leads to Monday."
              />
            ) : null}
            {awaitingEnrich ? (
              <PrimaryAction
                full
                label={enrichArmed ? "Confirm enrich" : `Enrich ${shortlisted}`}
                onClick={onEnrich}
                busy={pending}
                disabled={shortlisted === 0}
                tone={enrichArmed ? "alarm" : "neutral"}
                reason={
                  shortlisted === 0
                    ? "Nothing is shortlisted. Restore a contact to enrich it."
                    : enrichArmed
                      ? `Enrich ${shortlisted} contacts, ${shortlisted} Apollo credits.`
                      : "Only shortlisted contacts are enriched. One more click confirms the spend."
                }
              />
            ) : null}
            {resumable ? (
              <PrimaryAction
                full
                label={run.status === "interrupted" ? "Resume" : "Retry stage"}
                onClick={onResume}
                busy={pending}
              />
            ) : null}
            {cancellable ? (
              <button
                type="button"
                onClick={onCancel}
                disabled={pending || run.cancel_requested}
                className="btn btn-line mt-2 w-full"
              >
                {run.cancel_requested ? "Cancel requested" : "Cancel"}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>

      {run.error ? <p className="mt-5 text-[14px] leading-snug text-alarm">{run.error}</p> : null}
      {run.status === "interrupted" ? (
        <p className="mt-4 max-w-2xl text-[14px] leading-relaxed text-ink-soft">
          The process stopped during this run. Resume continues from stage {run.stage} ({run.stage_name}). Completed
          calls are cached, so they are not paid for twice.
        </p>
      ) : null}
      {actionError ? <p className="mt-4 text-[14px] leading-snug text-alarm">{actionError}</p> : null}

      <div className="mt-8 max-w-md border-t border-line py-5">
        <h2 className="roboto text-[13px] text-ink-soft">Spend</h2>
        <SpendLedger providers={providers} reservation={run.reservation} spend={run.spend} />
      </div>
    </section>
  );
}

function SpendLedger({
  providers,
  reservation,
  spend,
}: {
  providers: string[];
  reservation: RunOut["reservation"];
  spend: RunOut["spend"];
}) {
  const rows = providers.filter((provider) => (spend[provider] ?? 0) !== 0 || (reservation[provider] ?? 0) !== 0);
  if (rows.length === 0) return <p className="mt-3 text-[15px]">No paid calls</p>;
  return (
    <div className="mt-3">
      <div className="grid grid-cols-[minmax(0,1fr)_4.5rem_5.5rem] gap-x-4 roboto text-[12px] text-ink-soft">
        <span>Provider</span>
        <span className="text-right">Spent</span>
        <span className="text-right">Reserved</span>
      </div>
      <ul className="mt-1 border-t border-line">
        {rows.map((provider) => (
          <li
            key={provider}
            className="grid grid-cols-[minmax(0,1fr)_4.5rem_5.5rem] gap-x-4 border-b border-line py-2 text-[15px] tabular-nums"
          >
            <span>{PROVIDER_NAME[provider] ?? provider}</span>
            <span className="text-right">{fmtNumber(spend[provider] ?? 0)}</span>
            <span className="text-right">{fmtNumber(reservation[provider] ?? 0)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
