import { CHANNEL_NAMES } from "../lib/protocol";

interface Props {
  signalQuality?: Record<string, number>;
  fitStatus?: "good" | "adjust" | "poor";
  motionArtifact?: boolean;
  jawClench?: boolean;
}

export function FitTool({ signalQuality, fitStatus, motionArtifact, jawClench }: Props) {
  const statusColor = fitStatus === "good" ? "var(--status-good)"
    : fitStatus === "adjust" ? "var(--status-warn)"
    : "var(--status-bad)";

  return (
    <div className="p-3 border-b" style={{ borderColor: "var(--border)" }}>
      <div className="flex items-center gap-6">
        {/* Head diagram placeholder */}
        <svg width="80" height="80" viewBox="0 0 80 80" className="shrink-0">
          <ellipse cx="40" cy="42" rx="28" ry="34" fill="none" stroke="var(--border)" strokeWidth="1.5" />
          <polygon points="40,4 36,14 44,14" fill="none" stroke="var(--border)" strokeWidth="1" />
          {/* Electrode positions */}
          <circle cx="12" cy="42" r="5" fill={signalQuality?.TP9 && signalQuality.TP9 > 0.7 ? "var(--status-good)" : "var(--status-bad)"} opacity="0.8" />
          <circle cx="24" cy="24" r="5" fill={signalQuality?.AF7 && signalQuality.AF7 > 0.7 ? "var(--status-good)" : "var(--status-bad)"} opacity="0.8" />
          <circle cx="56" cy="24" r="5" fill={signalQuality?.AF8 && signalQuality.AF8 > 0.7 ? "var(--status-good)" : "var(--status-bad)"} opacity="0.8" />
          <circle cx="68" cy="42" r="5" fill={signalQuality?.TP10 && signalQuality.TP10 > 0.7 ? "var(--status-good)" : "var(--status-bad)"} opacity="0.8" />
        </svg>

        {/* Quality bars */}
        <div className="flex-1 grid grid-cols-2 gap-x-6 gap-y-1">
          {CHANNEL_NAMES.map((name) => {
            const q = signalQuality?.[name] ?? 0;
            const chColor = `var(--ch-${name.toLowerCase()})`;
            return (
              <div key={name} className="flex items-center gap-2">
                <span className="text-[11px] font-mono w-8" style={{ color: chColor }}>{name}</span>
                <div className="flex-1 h-1.5 rounded-sm" style={{ background: "var(--bg-input)" }}>
                  <div className="h-full rounded-sm transition-all" style={{ width: `${q * 100}%`, background: chColor, opacity: 0.8 }} />
                </div>
                <span className="text-[11px] font-mono w-8 text-right" style={{ color: "var(--text-secondary)" }}>
                  {Math.round(q * 100)}%
                </span>
              </div>
            );
          })}
        </div>

        {/* Status */}
        <div className="text-right">
          <div className="text-sm font-mono font-semibold uppercase" style={{ color: statusColor }}>
            {fitStatus ?? "---"}
          </div>
          <div className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
            Motion: {motionArtifact ? "⚠ MOVING" : "still"} | Jaw: {jawClench ? "⚠ CLENCH" : "clear"}
          </div>
        </div>
      </div>
    </div>
  );
}
