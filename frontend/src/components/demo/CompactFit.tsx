import { CHANNEL_NAMES } from "../../lib/protocol";

const CH_COLORS: Record<string, string> = {
  TP9: "var(--ch-tp9)",
  AF7: "var(--ch-af7)",
  AF8: "var(--ch-af8)",
  TP10: "var(--ch-tp10)",
};

interface Props {
  signalQuality?: Record<string, number>;
  headbandState?: { state: "ready" | "fitting" | "headband_off"; seconds_in_state: number };
}

export function CompactFit({ signalQuality, headbandState }: Props) {
  const stateColor = headbandState?.state === "ready" ? "var(--status-good)"
    : headbandState?.state === "fitting" ? "var(--status-warn)"
    : "var(--status-bad)";

  const stateLabel = headbandState?.state === "ready" ? "READY"
    : headbandState?.state === "fitting" ? "FITTING"
    : headbandState?.state === "headband_off" ? "OFF"
    : "---";

  return (
    <div className="flex items-center gap-2">
      <div className="flex items-center gap-1">
        {CHANNEL_NAMES.map((name) => {
          const q = signalQuality?.[name] ?? 0;
          const good = q > 0.7;
          return (
            <div
              key={name}
              title={`${name}: ${Math.round(q * 100)}%`}
              className="w-2 h-2 rounded-full"
              style={{
                background: good ? CH_COLORS[name] : "var(--status-bad)",
                opacity: good ? 1 : 0.4,
              }}
            />
          );
        })}
      </div>
      <span
        className="text-[9px] uppercase px-1.5 py-0.5 border font-mono"
        style={{ color: stateColor, borderColor: stateColor }}
      >
        {stateLabel}
      </span>
    </div>
  );
}
