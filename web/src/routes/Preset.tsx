import * as Tabs from "@radix-ui/react-tabs";
import { useEffect, useState } from "react";
import { ApiError } from "../api/client";
import { usePresetSettings, usePresets, useResetPresetSettings, useSavePresetSettings } from "../api/queries";
import type { PresetSettings, VerticalSettings } from "../api/types";
import { Hint } from "../components/Hint";

export function PresetPage() {
  const presets = usePresets();
  const settings = usePresetSettings();
  const save = useSavePresetSettings();
  const reset = useResetPresetSettings();
  const [draft, setDraft] = useState<PresetSettings | null>(null);
  const [texts, setTexts] = useState<Record<string, string>>({});
  const [verticalId, setVerticalId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [resetArmed, setResetArmed] = useState(false);

  useEffect(() => {
    if (settings.data && draft === null) applyDocument(settings.data);
  }, [settings.data, draft]);

  function applyDocument(next: PresetSettings) {
    setDraft(next);
    setTexts(textMap(next));
    setSaved(false);
    setResetArmed(false);
    setError(null);
  }

  function touch() {
    setSaved(false);
    setResetArmed(false);
    setError(null);
  }

  if (settings.isPending || presets.isPending) {
    return <p className="py-16 text-[15px] text-ink-soft">Loading preset</p>;
  }
  if (settings.isError || !draft) {
    return <p className="py-16 text-[15px] text-alarm">Could not load the preset. {String(settings.error ?? "")}</p>;
  }

  const preset = presets.data?.[0];
  const vertical = draft.verticals.find((item) => item.id === verticalId) ?? draft.verticals[0];

  function saveNow() {
    const body = documentFrom(draft!, texts);
    setError(null);
    save.mutate(body, {
      onSuccess: (next) => {
        setDraft(next);
        setTexts(textMap(next));
        setSaved(true);
        setResetArmed(false);
      },
      onError: (err) => setError(errorText(err)),
    });
  }

  return (
    <div className="pt-6 sm:pt-8">
      <header className="max-w-2xl">
        <p className="text-[13px] text-ink-soft">Preset</p>
        <h1 className="mt-2 font-serif text-[3rem] leading-[0.95] tracking-[-0.02em] sm:text-[3.5rem]">
          {preset?.name ?? "The Underline"}
        </h1>
        <p className="mt-3 text-[15px] text-ink-soft">
          {preset ? `${preset.place} · ${preset.year}` : "Miami"}
        </p>
        <p className="mt-4 max-w-xl text-[16px] leading-relaxed">
          Search titles, locations, and the Monday board live here. A new run starts from these values. Reset restores
          the originals that ship with the app.
        </p>
      </header>

      <section className="mt-12">
        <h2 className="font-serif text-[1.75rem] leading-none tracking-[-0.02em]">Monday</h2>
        <div className="mt-5 grid gap-6 sm:grid-cols-2">
          <Field
            label="Board id"
            hint="Numeric Monday board id. Prospecting runs use this after you save. Email and triage still use MASTER_BOARD_ID in .env."
            value={draft.board_id}
            onChange={(value) => {
              touch();
              setDraft({ ...draft, board_id: value });
            }}
          />
          <Field
            label="New leads group id"
            hint="Monday group id where new items are created. Prospecting runs use this after you save."
            value={draft.new_leads_group_id}
            onChange={(value) => {
              touch();
              setDraft({ ...draft, new_leads_group_id: value });
            }}
          />
        </div>
        <p className="mt-3 max-w-xl text-[14px] leading-relaxed text-ink-soft">
          Column ids are read from this board by name when you save.
        </p>

        <details className="mt-8 border-t border-line pt-5">
          <summary className="cursor-pointer font-serif text-[1.35rem] leading-none">Protected accounts</summary>
          <div className="mt-4 grid gap-8 lg:grid-cols-2">
            <Lines
              label="Protected groups"
              hint="One Monday group id per line. A company already in one of these groups is not contacted again."
              value={texts.protected_groups ?? ""}
              onChange={(value) => {
                touch();
                setTexts((prev) => ({ ...prev, protected_groups: value }));
              }}
            />
            <Lines
              label="Protected statuses"
              hint="One status label per line, matched without case. Replied, Meeting Set, and Proposal Sent are the usual set."
              value={texts.protected_statuses ?? ""}
              onChange={(value) => {
                touch();
                setTexts((prev) => ({ ...prev, protected_statuses: value }));
              }}
            />
          </div>
        </details>
      </section>

      {vertical ? (
        <section className="mt-14">
          <h2 className="font-serif text-[1.75rem] leading-none tracking-[-0.02em]">Search</h2>
          <Tabs.Root value={vertical.id} onValueChange={setVerticalId} className="mt-6">
            <Tabs.List className="flex flex-wrap gap-x-8 gap-y-2 border-b border-line" aria-label="Verticals">
              {draft.verticals.map((item) => (
                <Tabs.Trigger
                  key={item.id}
                  value={item.id}
                  className="-mb-px border-b-2 border-transparent pb-3 font-serif text-[1.35rem] leading-none text-ink-soft data-[state=active]:border-ink data-[state=active]:text-ink"
                >
                  {item.label}
                </Tabs.Trigger>
              ))}
            </Tabs.List>
          </Tabs.Root>
          <VerticalEditor
            key={vertical.id}
            vertical={vertical}
            texts={texts}
            onText={(key, value) => {
              touch();
              setTexts((prev) => ({ ...prev, [key]: value }));
            }}
            onVertical={(next) => {
              touch();
              setDraft({
                ...draft,
                verticals: draft.verticals.map((item) => (item.id === next.id ? next : item)),
              });
            }}
          />
        </section>
      ) : null}

      <div className="mt-12 border-t border-line py-4">
        <div className="flex flex-wrap items-center gap-3">
          <button type="button" className="btn btn-ink" disabled={save.isPending} onClick={saveNow}>
            {save.isPending ? "Saving…" : "Save preset"}
          </button>
          <button
            type="button"
            className="btn btn-line"
            disabled={reset.isPending}
            onClick={() => {
              setError(null);
              if (!resetArmed) {
                setResetArmed(true);
                return;
              }
              reset.mutate(undefined, {
                onSuccess: (next) => applyDocument(next),
                onError: (err) => setError(errorText(err)),
              });
            }}
          >
            {resetArmed ? "Confirm reset" : "Reset to defaults"}
          </button>
          {saved ? <span className="text-[14px] text-ink-soft">Saved</span> : null}
        </div>
        {resetArmed ? (
          <p className="mt-3 max-w-xl text-[13px] leading-snug text-ink-soft">
            This drops the saved preset and restores the originals from code. Runs already started keep the settings they
            used.
          </p>
        ) : null}
        {error ? <p className="mt-3 text-[14px] leading-snug text-alarm">{error}</p> : null}
      </div>
    </div>
  );
}

function VerticalEditor({
  vertical,
  texts,
  onText,
  onVertical,
}: {
  vertical: VerticalSettings;
  texts: Record<string, string>;
  onText: (key: string, value: string) => void;
  onVertical: (next: VerticalSettings) => void;
}) {
  const apollo = vertical.source_kind === "apollo_people";
  const research = vertical.source_kind === "research_events";

  return (
    <div className="mt-8 grid gap-12">
      {apollo && vertical.monday_vertical !== "from_research" ? (
        <Field
          label="Monday vertical label"
          hint="The Vertical dropdown label written on each new Monday item."
          value={vertical.monday_vertical}
          onChange={(value) => onVertical({ ...vertical, monday_vertical: value })}
        />
      ) : null}

      <div className="grid gap-8 lg:grid-cols-2">
        <Lines
          label="Search titles"
          hint="One title per line. Apollo people search uses this list."
          value={texts[`${vertical.id}:titles`] ?? ""}
          onChange={(value) => onText(`${vertical.id}:titles`, value)}
          rows={12}
        />
        <Lines
          label="Seniorities"
          hint="One Apollo seniority per line, such as director, vp, or c_suite."
          value={texts[`${vertical.id}:seniorities`] ?? ""}
          onChange={(value) => onText(`${vertical.id}:seniorities`, value)}
          rows={12}
        />
      </div>

      {apollo ? (
        <div className="grid gap-8 lg:grid-cols-2">
          <Lines
            label="Org keywords"
            hint="One company keyword per line. The org-keyword path spends one Apollo credit per results page."
            value={texts[`${vertical.id}:keywords`] ?? ""}
            onChange={(value) => onText(`${vertical.id}:keywords`, value)}
          />
          <Lines
            label="Org locations"
            hint="One company headquarters location per line."
            value={texts[`${vertical.id}:org_locations`] ?? ""}
            onChange={(value) => onText(`${vertical.id}:org_locations`, value)}
          />
        </div>
      ) : null}

      {apollo
        ? (vertical.person_location_tiers ?? []).map((tier) => (
            <Lines
              key={tier.tier}
              label={`Person locations, tier ${tier.tier}`}
              hint="One place per line. Tier 1 is searched first. A run's location tier stops the search at that tier."
              value={texts[`${vertical.id}:tier:${tier.tier}`] ?? ""}
              onChange={(value) => onText(`${vertical.id}:tier:${tier.tier}`, value)}
            />
          ))
        : null}

      {research ? (
        <>
          <Field
            label="Event seed"
            hint="JSON file under data/. The run reads the next events from this file."
            value={vertical.seed_path}
            onChange={(value) => onVertical({ ...vertical, seed_path: value })}
          />
          <div className="grid gap-8 lg:grid-cols-2">
            <Lines
              label="Florida person locations"
              hint="Used when Florida person only is on. One place per line."
              value={texts[`${vertical.id}:florida`] ?? ""}
              onChange={(value) => onText(`${vertical.id}:florida`, value)}
            />
            <Lines
              label="US person locations"
              hint="Used when Florida person only is off and a US person is still required."
              value={texts[`${vertical.id}:us`] ?? ""}
              onChange={(value) => onText(`${vertical.id}:us`, value)}
            />
          </div>
        </>
      ) : null}

    </div>
  );
}

function Field({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block">
      <span className="text-[15px]">
        <Hint text={hint}>{label}</Hint>
      </span>
      <input className="textline mt-2" value={value} spellCheck={false} aria-label={label} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function Lines({
  label,
  hint,
  value,
  onChange,
  rows = 8,
}: {
  label: string;
  hint: string;
  value: string;
  onChange: (value: string) => void;
  rows?: number;
}) {
  return (
    <label className="block">
      <span className="text-[15px]">
        <Hint text={hint}>{label}</Hint>
      </span>
      <textarea className="lines mt-2" rows={rows} value={value} spellCheck={false} aria-label={label} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function textMap(settings: PresetSettings): Record<string, string> {
  const texts: Record<string, string> = {
    protected_groups: settings.protected_group_ids.join("\n"),
    protected_statuses: settings.protected_status_labels.join("\n"),
  };
  for (const vertical of settings.verticals) {
    texts[`${vertical.id}:titles`] = (vertical.titles ?? []).join("\n");
    texts[`${vertical.id}:seniorities`] = (vertical.seniorities ?? []).join("\n");
    texts[`${vertical.id}:keywords`] = (vertical.org_keyword_tags ?? []).join("\n");
    texts[`${vertical.id}:org_locations`] = (vertical.org_locations ?? []).join("\n");
    texts[`${vertical.id}:florida`] = (vertical.florida_person_locations ?? []).join("\n");
    texts[`${vertical.id}:us`] = (vertical.us_person_locations ?? []).join("\n");
    for (const tier of vertical.person_location_tiers ?? []) {
      texts[`${vertical.id}:tier:${tier.tier}`] = (tier.locations ?? []).join("\n");
    }
  }
  return texts;
}

function lines(text: string): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || seen.has(line)) continue;
    seen.add(line);
    out.push(line);
  }
  return out;
}

function documentFrom(draft: PresetSettings, texts: Record<string, string>): PresetSettings {
  return {
    ...draft,
    board_id: draft.board_id.trim(),
    new_leads_group_id: draft.new_leads_group_id.trim(),
    protected_group_ids: lines(texts.protected_groups ?? ""),
    protected_status_labels: lines(texts.protected_statuses ?? ""),
    verticals: draft.verticals.map((vertical) => ({
      ...vertical,
      monday_vertical: vertical.monday_vertical.trim(),
      seed_path: vertical.seed_path.trim(),
      titles: lines(texts[`${vertical.id}:titles`] ?? ""),
      seniorities: lines(texts[`${vertical.id}:seniorities`] ?? ""),
      org_keyword_tags: lines(texts[`${vertical.id}:keywords`] ?? ""),
      org_locations: lines(texts[`${vertical.id}:org_locations`] ?? ""),
      florida_person_locations: lines(texts[`${vertical.id}:florida`] ?? ""),
      us_person_locations: lines(texts[`${vertical.id}:us`] ?? ""),
      person_location_tiers: (vertical.person_location_tiers ?? []).map((tier) => ({
        tier: tier.tier,
        locations: lines(texts[`${vertical.id}:tier:${tier.tier}`] ?? ""),
      })),
    })),
  };
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Unknown error";
}
