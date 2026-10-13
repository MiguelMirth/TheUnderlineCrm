import type { ReactNode } from "react";

// A visible ? next to the label. Hover or focus shows the explanation.
export function Hint({ text, children }: { text: string; children?: ReactNode }) {
  if (!text) return <>{children}</>;
  return (
    <span className="hint">
      {children}
      <button type="button" className="hint-mark" aria-label={text}>
        <span aria-hidden>?</span>
        <span className="hint-tip" role="tooltip">
          {text}
        </span>
      </button>
    </span>
  );
}
