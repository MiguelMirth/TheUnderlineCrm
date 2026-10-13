import * as Tabs from "@radix-ui/react-tabs";
import { useCallback, useMemo, useState } from "react";
import { ApiError } from "../api/client";
import { useDecide, useDeleteRun, useEnrich, useHealth, useLeads, usePush, useRun, useRunAction, useRunEvents } from "../api/queries";
import { LIVE_STATUSES, type LeadAction, type LeadOut, type PushResult, type RefusedLead, type RunOut } from "../api/types";
import { LeadDetail } from "../components/LeadDetail";
import { LeadTable } from "../components/LeadTable";
import { PushDialog } from "../components/PushDialog";
import { RunHeader } from "../components/RunHeader";
import { fmtTime } from "../lib/format";
import { navigate } from "../lib/router";

type FilterKey = "failed" | "shortlist" | "needs_review" | "passed" | "rejected" | "approved" | "pushed";

// Each tab is a view over the run's leads, in the order a lead moves through the run.
const FILTERS: { key: FilterKey; label: string; match: (lead: LeadOut) => boolean }[] = [
  {
    key: "failed",
    label: "Failed",
    match: (l) => ["qa_failed", "llm_failed", "post_qa_failed", "blocked"].includes(l.state),
  },
  { key: "shortlist", label: "Shortlist", match: (l) => l.state === "shortlisted" },
  { key: "needs_review", label: "Needs review", match: (l) => l.state === "needs_review" },
  {
    key: "passed",
    label: "Passed",
    match: (l) => l.state === "needs_review" && l.approvable,
  },
  { key: "rejected", label: "Rejected", match: (l) => l.state === "rejected" },
  { key: "approved", label: "Approved", match: (l) => l.state === "approved" },
  { key: "pushed", label: "Pushed", match: (l) => l.state === "pushed" || l.state === "push_failed" },
];

const EMPTY_TEXT: Record<FilterKey, string> = {
  needs_review: "Nothing waiting for a decision.",
  shortlist: "No companies are waiting at the shortlist pause.",
  passed: "No lead has cleared every gate and the LLM check yet.",
  failed: "No lead failed a gate.",
  rejected: "No lead has been rejected.",
  approved: "No lead has been approved.",
  pushed: "Nothing has been pushed to Monday from this run.",
};

const VERB: Record<LeadAction, string> = { approve: "approved", reject: "rejected", restore: "restored" };

type Notice = { tone: "ok" | "alarm"; lines: string[] };

export function Review({ runId }: { runId: string }) {
  const run = useRun(runId);
  const leads = useLeads(runId);
  const events = useRunEvents(runId);
  const resume = useRunAction(runId, "resume");
  const cancel = useRunAction(runId, "cancel");
  const enrich = useEnrich(runId);
  const decide = useDecide(runId);
  const push = usePush(runId);
  const remove = useDeleteRun();
  const health = useHealth();

  const [filter, setFilter] = useState<FilterKey>("needs_review");
  const [openId, setOpenId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [notice, setNotice] = useState<Notice | null>(null);
  const [enrichArmed, setEnrichArmed] = useState(false);
  const [deleteArmed, setDeleteArmed] = useState(false);
  const [pushOpen, setPushOpen] = useState(false);
  const [pushResult, setPushResult] = useState<PushResult | null>(null);

  const allLeads = useMemo(() => leads.data ?? [], [leads.data]);
  const openLead = openId ? (allLeads.find((l) => l.id === openId) ?? null) : null;
  const brandById = useMemo(() => new Map(allLeads.map((l) => [l.id, l.shelf_brand || l.email])), [allLeads]);

  const toggleOne = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleMany = useCallback((ids: string[], on: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      for (const id of ids) {
        if (on) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  }, []);

  const applyDecision = useCallback(
    (action: LeadAction, ids: string[]) => {
      if (ids.length === 0) return;
      setNotice(null);
      decide.mutate(
        { action, lead_ids: ids },
        {
          onSuccess: (result) => {
            setSelected(new Set());
            if (result.refused.length > 0) {
              setNotice({ tone: "alarm", lines: refusedLines(result.refused, brandById) });
            } else {
              setNotice({ tone: "ok", lines: [`${result.updated.length} lead(s) ${VERB[action]}.`] });
            }
          },
          onError: (error) => {
            const refused = refusedFromError(error);
            const lines = refused.length
              ? [errorMessage(error), ...refusedLines(refused, brandById)]
              : [errorMessage(error)];
            setNotice({ tone: "alarm", lines });
          },
        },
      );
    },
    [brandById, decide],
  );

  if (run.isPending) {
    return <p className="py-16 text-[15px] text-ink-soft">Loading run</p>;
  }
  if (run.isError) {
    const notFound = run.error instanceof ApiError && run.error.status === 404;
    return (
      <div className="py-16">
        <p className="text-[15px] text-alarm">{notFound ? `No run ${runId}.` : `Could not load run. ${String(run.error)}`}</p>
        <a
          href="/"
          className="mt-4 inline-block text-[15px] underline decoration-line underline-offset-4"
          onClick={(e) => {
            e.preventDefault();
            navigate("/");
          }}
        >
          Back to Gather
        </a>
      </div>
    );
  }

  const current: RunOut = run.data;
  const actionError = [resume.error, cancel.error, enrich.error, remove.error].find(Boolean);
  const selectedIds = [...selected];
  const pushCount = allLeads.filter((lead) => lead.state === "approved" || lead.state === "push_failed").length;
  const contractProblems = health.data?.board_contract_problems ?? [];

  return (
    <div className="pt-6 sm:pt-8">
      <a
        href="/"
        onClick={(e) => {
          e.preventDefault();
          navigate("/");
        }}
        className="text-[14px] text-ink-soft hover:text-ink"
      >
        ← Gather
      </a>

      <div className="mt-6">
        <RunHeader
          run={current}
          onResume={() => resume.mutate()}
          onCancel={() => cancel.mutate()}
          enrichArmed={enrichArmed}
          pushCount={pushCount}
          onPush={() => {
            setPushResult(null);
            setPushOpen(true);
          }}
          onEnrich={() => {
            if (!enrichArmed) {
              setEnrichArmed(true);
              return;
            }
            setEnrichArmed(false);
            enrich.mutate();
          }}
          onDelete={() => {
            if (LIVE_STATUSES.includes(current.status)) return;
            if (!deleteArmed) {
              setDeleteArmed(true);
              return;
            }
            remove.mutate(runId, { onSuccess: () => navigate("/") });
          }}
          deleteArmed={deleteArmed}
          pending={resume.isPending || cancel.isPending || enrich.isPending || remove.isPending}
          actionError={actionError ? errorMessage(actionError) : undefined}
        />
      </div>

      <Tabs.Root
        value={filter}
        onValueChange={(v) => {
          setFilter(v as FilterKey);
          setSelected(new Set());
        }}
        className="mt-10"
      >
        <Tabs.List className="flex flex-wrap gap-x-6 gap-y-1 border-b border-line" aria-label="Lead states">
            {FILTERS.map((f) => {
              const count = allLeads.filter(f.match).length;
              return (
                <Tabs.Trigger
                  key={f.key}
                  value={f.key}
                  className="-mb-px flex items-baseline gap-2 border-b-2 border-transparent pb-3 text-[15px] text-ink-soft data-[state=active]:border-ink data-[state=active]:text-ink"
                >
                  {f.label}
                  <span className="tabular-nums">{count}</span>
                </Tabs.Trigger>
              );
            })}
          </Tabs.List>
      </Tabs.Root>

      <div className="mt-5">
        <DecisionBar
          count={selectedIds.length}
          busy={decide.isPending}
          onAction={(action) => applyDecision(action, selectedIds)}
          onClear={() => setSelected(new Set())}
        />
        {notice ? (
          <div
            className={`mt-4 space-y-1 border-l-2 pl-3 text-[14px] leading-snug ${notice.tone === "alarm" ? "border-alarm text-alarm" : "border-ink text-ink"}`}
            role="status"
          >
            {notice.lines.map((line, index) => (
              <p key={index}>{line}</p>
            ))}
          </div>
        ) : null}
      </div>

      <div className="mt-2">
        {leads.isPending ? (
          <p className="py-8 text-[15px] text-ink-soft">Loading leads</p>
        ) : leads.isError ? (
          <p className="py-8 text-[15px] text-alarm">Could not load leads.</p>
        ) : allLeads.length === 0 ? (
          <p className="py-8 text-[15px] text-ink-soft">
            No leads in this run yet.
            {current.status === "complete" ? " The run finished without finding any." : ""}
          </p>
        ) : (
          <FilteredLeads
            filter={FILTERS.find((f) => f.key === filter) ?? FILTERS[0]}
            leads={allLeads}
            onOpen={setOpenId}
            selected={selected}
            onToggle={toggleOne}
            onToggleAll={toggleMany}
          />
        )}
      </div>

      <details className="group mt-14 border-t border-line pt-6">
        <summary className="flex cursor-pointer items-baseline justify-between gap-4">
          <span className="font-serif text-[1.75rem] leading-none tracking-[-0.02em]">Run log</span>
          <span className="font-serif text-[1.35rem] leading-none text-ink-soft group-open:hidden" aria-hidden>
            +
          </span>
          <span className="hidden font-serif text-[1.35rem] leading-none text-ink-soft group-open:inline" aria-hidden>
            –
          </span>
        </summary>
        {events.isPending ? (
          <p className="mt-4 text-[14px] text-ink-soft">Loading log</p>
        ) : (
          <ol className="mt-4 max-h-80 overflow-y-auto border-t border-line text-[14px]">
            {(events.data ?? []).map((e) => (
              <li key={e.id} className="grid grid-cols-1 gap-1 border-b border-line py-2.5 sm:grid-cols-[8.5rem_minmax(0,1fr)] sm:gap-4">
                <span className="text-ink-soft tabular-nums">{fmtTime(e.ts)}</span>
                <span className={e.level === "error" ? "text-alarm" : e.level === "warn" ? "text-ink" : "text-ink-soft"}>
                  {e.message}
                </span>
              </li>
            ))}
          </ol>
        )}
      </details>

      <PushDialog
        open={pushOpen}
        count={pushCount}
        liveEnabled={health.data?.live_push_enabled === true}
        contractProblems={contractProblems}
        busy={push.isPending}
        result={pushResult}
        error={push.isError ? errorMessage(push.error) : null}
        onClose={() => setPushOpen(false)}
        onConfirm={() => {
          push.mutate(undefined, { onSuccess: (result) => setPushResult(result) });
        }}
      />

      <LeadDetail
        lead={openLead}
        onClose={() => setOpenId(null)}
        busy={decide.isPending}
        decisionError={openLead && decide.isError && decide.variables?.lead_ids.includes(openLead.id) ? errorMessage(decide.error) : null}
        onDecide={(action) => {
          if (openLead) applyDecision(action, [openLead.id]);
        }}
      />
    </div>
  );
}

function DecisionBar({
  count,
  busy,
  onAction,
  onClear,
}: {
  count: number;
  busy: boolean;
  onAction: (action: LeadAction) => void;
  onClear: () => void;
}) {
  const disabled = count === 0 || busy;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <span className="mr-1 text-[13px] text-ink-soft tabular-nums">
        {count === 0 ? "Select leads. Approve applies to all of them, or to none." : `${count} selected`}
      </span>
      <button type="button" onClick={() => onAction("approve")} disabled={disabled} className="btn btn-ink btn-sm">
        Approve
      </button>
      <button type="button" onClick={() => onAction("reject")} disabled={disabled} className="btn btn-line btn-sm">
        Reject
      </button>
      <button type="button" onClick={() => onAction("restore")} disabled={disabled} className="btn btn-line btn-sm">
        Restore
      </button>
      {count > 0 ? (
        <button type="button" onClick={onClear} className="btn btn-quiet btn-sm">
          Clear
        </button>
      ) : null}
    </div>
  );
}

function FilteredLeads({
  filter,
  leads,
  onOpen,
  selected,
  onToggle,
  onToggleAll,
}: {
  filter: (typeof FILTERS)[number];
  leads: LeadOut[];
  onOpen: (id: string) => void;
  selected: Set<string>;
  onToggle: (id: string) => void;
  onToggleAll: (ids: string[], on: boolean) => void;
}) {
  const visible = leads.filter(filter.match);
  if (visible.length === 0) {
    return <p className="py-8 text-[15px] text-ink-soft">{EMPTY_TEXT[filter.key]}</p>;
  }
  return (
    <LeadTable
      leads={visible}
      onOpen={onOpen}
      selected={selected}
      onToggle={onToggle}
      onToggleAll={onToggleAll}
    />
  );
}

function refusedFromError(error: unknown): RefusedLead[] {
  if (error instanceof ApiError && error.detail && typeof error.detail === "object" && "refused" in error.detail) {
    const refused = (error.detail as { refused: unknown }).refused;
    return Array.isArray(refused) ? (refused as RefusedLead[]) : [];
  }
  return [];
}

function refusedLines(refused: RefusedLead[], brandById: Map<string, string>): string[] {
  return refused.map((r) => `${brandById.get(r.lead_id) ?? r.lead_id}: ${r.reason}`);
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.detail && typeof error.detail === "object" && "message" in error.detail) {
      return String((error.detail as { message: unknown }).message);
    }
    return error.message;
  }
  if (error instanceof Error) return error.message;
  return "That action did not complete.";
}
