export function TrashButton({
  armed,
  disabled,
  onClick,
}: {
  armed: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  const label = armed ? "Click again to remove this run" : "Remove this run";
  return (
    <button
      type="button"
      aria-label={label}
      title={disabled ? "Cancel this run before removing it." : label}
      disabled={disabled}
      onClick={onClick}
      data-armed={armed ? "true" : "false"}
      className="icon-btn"
    >
      <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden>
        <path d="M3.2 4.2h9.6" stroke="currentColor" strokeWidth="1.2" />
        <path d="M6.2 4.1V2.8h3.6v1.3" stroke="currentColor" strokeWidth="1.2" />
        <path d="M4.2 4.4l.6 9h6.4l.6-9" stroke="currentColor" strokeWidth="1.2" />
        <path d="M6.6 6.4v4.6M9.4 6.4v4.6" stroke="currentColor" strokeWidth="1.2" />
      </svg>
    </button>
  );
}
