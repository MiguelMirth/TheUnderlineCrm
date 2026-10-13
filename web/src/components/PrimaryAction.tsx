import type { ReactNode } from "react";

// The next action. The label is on the button. The blocking reason sits under it.
export function PrimaryAction({
  label,
  disabled,
  busy,
  onClick,
  reason,
  tone = "neutral",
  full = false,
}: {
  label: string;
  disabled?: boolean;
  busy?: boolean;
  onClick: () => void;
  reason?: ReactNode;
  tone?: "neutral" | "alarm";
  full?: boolean;
}) {
  const isDisabled = disabled || busy;
  return (
    <div className={full ? "w-full" : "w-full sm:max-w-xs"}>
      <button type="button" onClick={onClick} disabled={isDisabled} className={`btn btn-ink ${full ? "w-full" : ""}`}>
        {busy ? `${label}…` : label}
      </button>
      {reason ? (
        <p className={`mt-2 text-[13px] leading-snug ${tone === "alarm" ? "text-alarm" : "text-ink-soft"}`}>{reason}</p>
      ) : null}
    </div>
  );
}
