import { useState } from "react";

// The box can be empty while typing. A blank field becomes 0 when it loses focus,
// so clearing a number does not leave a 0 in front of the next digit.
export function NumberField({
  value,
  onChange,
  label,
  className = "num",
}: {
  value: number;
  onChange: (next: number) => void;
  label?: string;
  className?: string;
}) {
  const [text, setText] = useState<string | null>(null);
  const shown = text ?? String(value);

  return (
    <input
      type="text"
      inputMode="numeric"
      autoComplete="off"
      aria-label={label}
      className={className}
      value={shown}
      onChange={(event) => {
        const raw = event.target.value;
        if (raw === "") {
          setText("");
          return;
        }
        if (!/^\d+$/.test(raw)) return;
        const normalized = raw.replace(/^0+(?=\d)/, "");
        setText(normalized);
        onChange(Number.parseInt(normalized, 10));
      }}
      onBlur={() => {
        if (shown === "") onChange(0);
        setText(null);
      }}
    />
  );
}
