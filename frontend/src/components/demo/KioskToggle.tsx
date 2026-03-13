interface Props {
  enabled: boolean;
  connected: boolean;
  onToggle: (enabled: boolean) => void;
}

export function KioskToggle({ enabled, connected, onToggle }: Props) {
  return (
    <button
      type="button"
      onClick={() => onToggle(!enabled)}
      className="flex items-center gap-2 text-[11px] font-mono px-2 py-0.5"
      style={{
        color: enabled
          ? connected ? "var(--status-good)" : "var(--status-warn)"
          : "var(--text-dim)",
        background: enabled ? "rgba(255,255,255,0.05)" : "transparent",
        border: `1px solid ${enabled ? "var(--border)" : "transparent"}`,
      }}
    >
      <span
        className="inline-block w-1.5 h-1.5 rounded-full"
        style={{
          background: enabled
            ? connected ? "var(--status-good)" : "var(--status-warn)"
            : "var(--text-dim)",
          boxShadow: connected && enabled ? "0 0 4px var(--status-good)" : "none",
        }}
      />
      KIOSK {enabled ? (connected ? "LIVE" : "connecting...") : "OFF"}
    </button>
  );
}
