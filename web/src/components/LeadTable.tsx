import type { LeadOut } from "../api/types";
import { fmtNumber, statusLabel } from "../lib/format";

const ALARM_STATES = new Set(["qa_failed", "llm_failed", "post_qa_failed", "blocked", "push_failed"]);

// The first failing gate, plus a count of the rest. The side panel shows the full trail.
function qaSummary(lead: LeadOut): { text: string; failed: boolean } | null {
  if ((lead.gates ?? []).length === 0) return null;
  const failing = lead.gates.filter((g) => !g.passed);
  if (failing.length === 0) return { text: "Gates passed", failed: false };
  const [first, ...rest] = failing;
  const more = rest.length > 0 ? ` (+${rest.length} more)` : "";
  return { text: `${first.gate_id}: ${first.reason || "failed"}${more}`, failed: true };
}

function llmField(lead: LeadOut, key: string): string {
  const value = lead.llm?.[key];
  return typeof value === "string" ? value : "";
}

export function LeadTable({
  leads,
  onOpen,
  selected,
  onToggle,
  onToggleAll,
}: {
  leads: LeadOut[];
  onOpen: (id: string) => void;
  selected: Set<string>;
  onToggle: (id: string) => void;
  onToggleAll: (ids: string[], on: boolean) => void;
}) {
  const allOn = leads.length > 0 && leads.every((lead) => selected.has(lead.id));

  return (
    <div>
      <div className="flex items-center gap-3 border-b border-line py-3">
        <input
          type="checkbox"
          aria-label="Select all visible leads"
          checked={allOn}
          onChange={(event) => onToggleAll(leads.map((lead) => lead.id), event.target.checked)}
        />
        <span className="text-[13px] text-ink-soft">
          {allOn ? "All visible selected" : `Select all ${leads.length}`}
        </span>
      </div>
      <ul>
        {leads.map((lead) => {
          const qa = qaSummary(lead);
          const reason = llmField(lead, "reason");
          const person = [lead.person_name, lead.title].filter(Boolean).join(" · ");
          const meta = [lead.email, lead.location].filter(Boolean).join(" · ");
          const alarm = ALARM_STATES.has(lead.state);
          const on = selected.has(lead.id);
          return (
            <li
              key={lead.id}
              className={`grid grid-cols-[1.05rem_minmax(0,1fr)_auto] items-start gap-x-4 border-b border-line py-4 ${on ? "bg-paper-sunk -mx-3 px-3" : ""}`}
            >
              <div className="pt-1.5">
                <input
                  type="checkbox"
                  aria-label={`Select ${lead.shelf_brand || lead.email}`}
                  checked={on}
                  onChange={() => onToggle(lead.id)}
                />
              </div>
              <button type="button" onClick={() => onOpen(lead.id)} className="min-w-0 text-left">
                <span className="block font-serif text-[1.45rem] leading-none tracking-[-0.02em]">
                  {lead.shelf_brand || "Unnamed"}
                </span>
                <span className="mt-1.5 block text-[14px] leading-snug">{person || "No name"}</span>
                <span className="mt-0.5 block truncate text-[13px] text-ink-soft">{meta || "No email"}</span>
                {qa ? (
                  <span className={`mt-1.5 block text-[13px] leading-snug ${qa.failed ? "text-alarm" : "text-ink-soft"}`}>
                    {qa.text}
                  </span>
                ) : null}
                {!lead.approvable && reason ? (
                  <span className="mt-1 line-clamp-2 block text-[13px] leading-snug text-ink-soft">{reason}</span>
                ) : null}
              </button>
              <div className="pt-1 text-right text-[14px] leading-snug">
                <p className={alarm ? "text-alarm" : undefined}>{statusLabel(lead.state)}</p>
                {lead.cost_spent > 0 ? (
                  <p className="text-[12px] text-ink-soft tabular-nums">{fmtNumber(lead.cost_spent)} spent</p>
                ) : null}
                {lead.monday_item_id ? <p className="text-[12px] text-ink-soft">Item {lead.monday_item_id}</p> : null}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
