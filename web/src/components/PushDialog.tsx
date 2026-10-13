import * as AlertDialog from "@radix-ui/react-alert-dialog";
import type { PushResult } from "../api/types";

// One confirmation. Confirm writes to Monday.
export function PushDialog({
  open,
  count,
  liveEnabled,
  contractProblems,
  busy,
  result,
  error,
  onClose,
  onConfirm,
}: {
  open: boolean;
  count: number;
  liveEnabled: boolean;
  contractProblems: string[];
  busy: boolean;
  result: PushResult | null;
  error: string | null;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const blockedReason = !liveEnabled
    ? "Monday writes are off. Set ENGINE_LIVE_PUSH_ENABLED to true and restart."
    : contractProblems[0] || "";
  const blocked = !liveEnabled || contractProblems.length > 0;

  return (
    <AlertDialog.Root open={open} onOpenChange={(next) => !next && onClose()}>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="fixed inset-0 z-40 bg-ink/40" />
        <AlertDialog.Content className="fixed top-1/2 left-1/2 z-50 w-[min(32rem,calc(100%-2rem))] -translate-x-1/2 -translate-y-1/2 border border-ink bg-paper p-6 focus:outline-none sm:p-8">
          <AlertDialog.Title className="font-serif text-[2rem] leading-none tracking-[-0.02em]">Push {count}</AlertDialog.Title>
          <AlertDialog.Description className="mt-3 text-[15px] leading-relaxed text-ink-soft">
            Write {count} approved lead(s) to Monday New Leads. Emails are rechecked first. A lead that already
            has a Monday item id is not created again.
          </AlertDialog.Description>

          {result ? (
            <div className="mt-4 space-y-1 text-[14px] leading-snug" role="status">
              <p>{result.message}</p>
              {result.rows
                .filter((row) => row.outcome === "failed" || row.outcome === "skipped")
                .slice(0, 8)
                .map((row) => (
                  <p key={row.lead_id} className="text-alarm">
                    {row.shelf_brand || row.email}: {row.reason}
                  </p>
                ))}
            </div>
          ) : null}
          {error ? <p className="mt-4 text-[14px] leading-snug text-alarm">{error}</p> : null}

          <div className="mt-6 flex flex-wrap gap-2">
            <button type="button" onClick={onConfirm} disabled={busy || count === 0 || blocked} className="btn btn-ink btn-sm">
              {busy ? "Writing…" : "Confirm write"}
            </button>
            <AlertDialog.Cancel className="btn btn-quiet btn-sm">Close</AlertDialog.Cancel>
          </div>
          {blockedReason ? <p className="mt-3 text-[13px] leading-snug text-ink-soft">{blockedReason}</p> : null}
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
