import type { Estimate as EstimateT, ProviderEstimate } from "../api/types";
import { fmtNumber } from "../lib/format";
import { Hint } from "./Hint";

const PROVIDER_NAME: Record<string, string> = {
  apollo: "Apollo",
  tavily: "Tavily",
  cursor: "Cursor",
  gemini: "Gemini",
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function refreshLabel(iso: string): string {
  const [year, month, day] = iso.slice(0, 10).split("-").map((part) => Number(part));
  if (!year || !month || !day) return iso;
  const showYear = year !== new Date().getFullYear();
  return `${day} ${MONTHS[month - 1]}${showYear ? ` ${year}` : ""}`;
}

// One row per provider: what this run would spend, and what is left.
export function Estimate({
  estimate,
  loading,
  error,
}: {
  estimate?: EstimateT;
  loading: boolean;
  error?: string;
}) {
  if (!estimate) {
    if (error) return <p className="text-[14px] leading-snug text-alarm">{error}</p>;
    return <p className="text-[14px] text-ink-soft">{loading ? "Working out the estimate" : "No estimate yet"}</p>;
  }
  return (
    <div>
      {error ? <p className="mb-3 text-[13px] leading-snug text-alarm">{error}</p> : null}
      {loading ? <p className="mb-3 text-[13px] text-ink-soft">Updating</p> : null}
      {estimate.providers.length === 0 ? (
        <p className="text-[14px] leading-snug text-ink-soft">This vertical spends nothing outside the free stages.</p>
      ) : (
        <>
          <div className="grid grid-cols-[minmax(0,1fr)_6.5rem] gap-x-3 text-[12px] leading-tight text-ink-soft">
            <span>This run</span>
            <span className="text-right">Remaining</span>
          </div>
          <ul className="mt-2">
            {estimate.providers.map((provider) => (
              <ProviderRow key={provider.provider} provider={provider} />
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function Remaining({ provider }: { provider: ProviderEstimate }) {
  if (provider.provider === "gemini") {
    return <Hint text="Free while Google accepts the request.">—</Hint>;
  }
  if (provider.remaining === null || provider.remaining === undefined) return <span className="text-ink-soft">—</span>;
  return <>{fmtNumber(provider.remaining)}</>;
}

function ProviderRow({ provider }: { provider: ProviderEstimate }) {
  const unit = provider.unit;
  return (
    <li className="border-t border-line py-3">
      <div className="grid grid-cols-[minmax(0,1fr)_6.5rem] items-baseline gap-x-3">
        <p className="text-[15px]">{PROVIDER_NAME[provider.provider] ?? provider.provider}</p>
        <p className="text-right text-[15px] tabular-nums">
          <Remaining provider={provider} />
        </p>
        <p className="text-[15px] tabular-nums">
          {provider.total === null || provider.total === undefined ? (
            <Hint text="Filled in when you measure.">—</Hint>
          ) : (
            `${fmtNumber(provider.total)} ${unit}`
          )}
        </p>
        <p className="text-right text-[12px] leading-snug text-ink-soft">
          {provider.refreshes_on ? `refreshes ${refreshLabel(provider.refreshes_on)}` : ""}
        </p>
      </div>
      {provider.lines.length > 0 ? (
        <ul className="mt-2 space-y-1 text-[13px] leading-snug text-ink-soft">
          {provider.lines.map((line) => (
            <li key={line.label} className="flex items-center justify-between gap-3">
              <span className="min-w-0">
                {line.note ? <Hint text={line.note}>{line.label}</Hint> : line.label}
              </span>
              {line.units === null || line.units === undefined ? null : (
                <span className="shrink-0 tabular-nums text-ink">{fmtNumber(line.units)}</span>
              )}
            </li>
          ))}
        </ul>
      ) : null}
      {provider.blocker ? <p className="mt-2 text-[13px] leading-snug text-alarm">{provider.blocker}</p> : null}
    </li>
  );
}
