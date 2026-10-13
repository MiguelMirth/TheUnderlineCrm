import type { ToggleSpec, ToggleValue } from "../api/types";
import { toggleStatus } from "../lib/format";
import { gateHint, gateLabel } from "../lib/hints";
import { Hint } from "./Hint";
import { NumberField } from "./NumberField";

export function ToggleList({
  toggles,
  values,
  onChange,
}: {
  toggles: ToggleSpec[];
  values: Record<string, ToggleValue>;
  onChange: (id: string, value: ToggleValue) => void;
}) {
  return (
    <ul className="border-y border-line">
      {toggles.map((spec) => {
        const value = values[spec.id] ?? spec.default;
        const status = toggleStatus(spec, value);
        const moved = status === "relaxed" || status === "tightened";
        return (
          <li key={spec.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-6 gap-y-2 border-b border-line py-3.5 last:border-b-0">
            <p className="min-w-0 text-[15px] leading-snug">
              <Hint text={gateHint(spec)}>{gateLabel(spec)}</Hint>
              {moved ? <span className="roboto ml-2 text-[13px] text-ink-soft">{status}</span> : null}
            </p>
            <Control spec={spec} value={value} onChange={(next) => onChange(spec.id, next)} />
          </li>
        );
      })}
    </ul>
  );
}

function Control({
  spec,
  value,
  onChange,
}: {
  spec: ToggleSpec;
  value: ToggleValue;
  onChange: (next: ToggleValue) => void;
}) {
  const label = spec.label;
  if (spec.kind === "bool") {
    const on = value === true;
    return (
      <div className="seg" role="group" aria-label={label}>
        <button type="button" aria-pressed={on} onClick={() => onChange(true)}>
          On
        </button>
        <button type="button" aria-pressed={!on} onClick={() => onChange(false)}>
          Off
        </button>
      </div>
    );
  }
  if (spec.kind === "int") {
    return (
      <NumberField label={label} value={Number(value)} onChange={onChange} className="num w-36" />
    );
  }
  return (
    <select
      value={String(value)}
      onChange={(event) => onChange(event.target.value)}
      aria-label={label}
      className="field w-44 text-[15px]"
    >
      {(spec.choices ?? []).map((choice) => (
        <option key={choice} value={choice}>
          {choice}
        </option>
      ))}
    </select>
  );
}
