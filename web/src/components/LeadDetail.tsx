import * as Dialog from "@radix-ui/react-dialog";
import type { LeadAction, LeadOut } from "../api/types";
import { fmtNumber, fmtTime, statusLabel } from "../lib/format";

// Side panel for one lead: the full gate trail, the LLM verdict, evidence, and the decision actions.
// Approve is disabled with the failing reason; the server enforces the same rule.
export function LeadDetail({
  lead,
  onClose,
  onDecide,
  busy = false,
  decisionError = null,
}: {
  lead: LeadOut | null;
  onClose: () => void;
  onDecide?: (action: LeadAction) => void;
  busy?: boolean;
  decisionError?: string | null;
}) {
  return (
    <Dialog.Root open={lead !== null} onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink/40" />
        <Dialog.Content className="fixed inset-y-0 right-0 z-50 flex h-dvh w-full max-w-xl flex-col border-l border-ink bg-paper focus:outline-none">
          {lead ? (
            <>
              <div className="flex items-start justify-between gap-4 px-6 pt-7 sm:px-8">
                <div className="min-w-0">
                  <Dialog.Title className="font-serif text-[2rem] leading-[1.05] tracking-[-0.02em]">
                    {lead.shelf_brand || "Unnamed brand"}
                  </Dialog.Title>
                  <Dialog.Description className="mt-2 text-[15px] leading-snug text-ink">
                    {lead.person_name || "No name"}
                    {lead.title ? ` · ${lead.title}` : ""}
                  </Dialog.Description>
                  <p className="roboto mt-1 text-[15px]">{statusLabel(lead.state)}</p>
                </div>
                <Dialog.Close className="btn btn-quiet shrink-0">Close</Dialog.Close>
              </div>

              <div className="mt-6 flex-1 overflow-y-auto px-6 pb-8 sm:px-8">
                <dl className="grid grid-cols-1 gap-x-8 gap-y-4 text-[14px] sm:grid-cols-2">
                  <Fact label="Email" value={lead.email} />
                  <Fact label="Domain" value={lead.domain} />
                  <Fact label="Location" value={lead.location} />
                  <Fact label="Vertical" value={lead.vertical} />
                  <Fact label="Cost spent" value={fmtNumber(lead.cost_spent)} />
                  <Fact label="Monday item" value={lead.monday_item_id} />
                  {lead.decided_by ? <Fact label="Decided by" value={lead.decided_by} /> : null}
                  {lead.decided_at ? <Fact label="Decided" value={fmtTime(lead.decided_at)} /> : null}
                </dl>
                {lead.push_error ? <p className="mt-4 text-[14px] leading-snug text-alarm">{lead.push_error}</p> : null}

                <section className="mt-8">
                  <h2 className="font-serif text-[1.5rem] leading-none">Gate trail</h2>
                  {lead.gates.length === 0 ? (
                    <p className="mt-3 text-[14px] text-ink-soft">No gates recorded yet.</p>
                  ) : (
                    <ol className="mt-3 border-t border-line">
                      {lead.gates.map((gate, index) => (
                        <li
                          key={`${gate.stage}-${gate.gate_id}-${index}`}
                          className="grid grid-cols-[4.25rem_minmax(0,1fr)_3.25rem] gap-3 border-b border-line py-2.5 text-[14px]"
                        >
                          <span className="text-ink-soft tabular-nums">Stage {gate.stage}</span>
                          <span className="min-w-0">
                            <span className="block">{gate.gate_id}</span>
                            {gate.reason ? <span className="mt-0.5 block text-[13px] leading-snug text-ink-soft">{gate.reason}</span> : null}
                          </span>
                          <span className={`text-right ${gate.passed ? "text-ink" : "text-alarm"}`}>
                            {gate.passed ? "Pass" : "Fail"}
                          </span>
                        </li>
                      ))}
                    </ol>
                  )}
                </section>

                <section className="mt-8">
                  <h2 className="font-serif text-[1.5rem] leading-none">LLM verdict</h2>
                  {lead.llm ? <Verdict llm={lead.llm} /> : <p className="mt-3 text-[14px] text-ink-soft">Not reviewed by the LLM yet.</p>}
                </section>

                <section className="mt-8">
                  <h2 className="font-serif text-[1.5rem] leading-none">Evidence</h2>
                  {(lead.evidence ?? []).length === 0 ? (
                    <p className="mt-3 text-[14px] text-ink-soft">No evidence snippets.</p>
                  ) : (
                    <ul className="mt-3 space-y-4">
                      {(lead.evidence ?? []).map((snippet, index) => (
                        <li key={index} className="border-l border-ink pl-3 text-[14px] leading-relaxed text-ink-soft">
                          {snippet}
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              </div>

              <div className="border-t border-line px-6 py-5 sm:px-8">
                <p className={`text-[14px] leading-snug ${lead.approvable ? "text-ink" : "text-alarm"}`}>
                  {lead.approvable ? "Ready to approve." : `Not approvable: ${lead.approve_blocker}`}
                </p>
                {decisionError ? <p className="mt-2 text-[13px] leading-snug text-alarm">{decisionError}</p> : null}
                <div className="mt-4 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => onDecide?.("approve")}
                    disabled={!onDecide || busy || !lead.approvable || lead.state === "approved"}
                    className="btn btn-ink btn-sm"
                  >
                    {lead.state === "approved" ? "Approved" : "Approve"}
                  </button>
                  {lead.state === "rejected" ? (
                    <button
                      type="button"
                      onClick={() => onDecide?.("restore")}
                      disabled={!onDecide || busy}
                      className="btn btn-line btn-sm"
                    >
                      Restore
                    </button>
                  ) : (
                    <button
                      type="button"
                      onClick={() => onDecide?.("reject")}
                      disabled={!onDecide || busy || lead.state === "pushed"}
                      className="btn btn-line btn-sm"
                    >
                      Reject
                    </button>
                  )}
                </div>
              </div>
            </>
          ) : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[13px] text-ink-soft">{label}</dt>
      <dd className="mt-0.5 break-words">{value || "—"}</dd>
    </div>
  );
}

function Verdict({ llm }: { llm: Record<string, unknown> }) {
  const strings = Object.entries(llm).filter((entry): entry is [string, string] => typeof entry[1] === "string" && entry[1] !== "");
  return (
    <div className="mt-3">
      {strings.length > 0 ? (
        <dl className="space-y-3">
          {strings.map(([key, value]) => (
            <div key={key}>
              <dt className="text-[13px] text-ink-soft">{labelFor(key)}</dt>
              <dd className="mt-0.5 text-[14px] leading-relaxed">{value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      <details className="mt-4">
        <summary className="cursor-pointer text-[13px] text-ink-soft">Raw verdict</summary>
        <pre className="mt-2 overflow-x-auto border border-line p-3 text-[12px] leading-relaxed">{JSON.stringify(llm, null, 2)}</pre>
      </details>
    </div>
  );
}

function labelFor(key: string): string {
  return key.replace(/_/g, " ");
}
