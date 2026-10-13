import { ApiError } from "../api/client";
import { useCrmStatus, useRefreshCrm } from "../api/queries";
import { fmtNumber, fmtTime } from "../lib/format";

// Shows when the Monday board was last read, whether it is stale, and the one manual refresh.
// The snapshot is a read-only copy used for the blocklist. Refresh is refused while a run is live.
export function CrmStrip({ liveRunId }: { liveRunId?: string | null }) {
  const status = useCrmStatus();
  const refresh = useRefreshCrm();
  const data = status.data;

  return (
    <section>
      <h2 className="font-serif text-[1.75rem] leading-none tracking-[-0.02em]">Monday board</h2>
      {status.isPending ? <p className="mt-3 text-[14px] text-ink-soft">Checking the snapshot</p> : null}
      {status.isError ? <p className="mt-3 text-[14px] text-alarm">Could not read the snapshot status.</p> : null}
      {data ? (
        <div className="mt-3 text-[15px] leading-snug">
          {data.fetched_at ? (
            <p>
              Read {fmtTime(data.fetched_at)}
              <span className="text-ink-soft">
                {" "}
                · {fmtNumber(data.board_rows)} {data.board_rows === 1 ? "row" : "rows"} · {fmtNumber(data.age_hours ?? 0)} h
                old
              </span>
              {data.stale ? <span className="roboto"> · stale</span> : null}
            </p>
          ) : (
            <p className="text-ink-soft">Not read yet. Start a run or press Refresh.</p>
          )}
          {!data.monday_key_set ? (
            <p className="mt-2 text-[14px] text-alarm">MONDAY_API_KEY is not set, so the board cannot be read.</p>
          ) : null}
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2">
        <button
          type="button"
          onClick={() => refresh.mutate()}
          disabled={refresh.isPending || Boolean(liveRunId) || !data?.monday_key_set}
          className="btn btn-line btn-sm"
        >
          {refresh.isPending ? "Reading the board…" : "Refresh board"}
        </button>
        {liveRunId ? <span className="text-[13px] text-ink-soft">Refresh waits until {liveRunId} finishes.</span> : null}
        {refresh.isError ? (
          <span className="text-[13px] text-alarm">
            {refresh.error instanceof ApiError ? refresh.error.message : "The refresh failed."}
          </span>
        ) : null}
      </div>
    </section>
  );
}
