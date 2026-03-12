import { useEffect, useRef } from "react";
import type { BciEvent } from "../../lib/protocol";

const KIND_COLORS: Record<string, string> = {
  single_blink: "var(--text-primary)",
  double_blink: "var(--text-primary)",
  triple_blink: "var(--text-primary)",
  clench: "var(--status-warn)",
};

const KIND_ACTIONS: Record<string, string> = {
  single_blink: "blink detected",
  double_blink: "kiosk → next",
  triple_blink: "light → toggle",
  clench: "clench detected",
};

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString("en-US", { hour12: false });
}

interface Props {
  events: BciEvent[];
}

export function EventLog({ events }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = 0;
    }
  }, [events.length]);

  const reversed = [...events].reverse();

  return (
    <div
      className="p-3"
      style={{ background: "var(--bg-panel)", border: "1px solid var(--border)" }}
    >
      <div
        className="text-[12px] uppercase tracking-wider mb-2"
        style={{ color: "var(--text-secondary)", fontFamily: "var(--font-label)" }}
      >
        Event Log
      </div>
      <div
        ref={scrollRef}
        className="overflow-y-auto font-mono text-[11px] space-y-0.5"
        style={{ maxHeight: 160, color: "var(--text-dim)" }}
      >
        {reversed.length === 0 && (
          <div style={{ color: "var(--text-dim)" }}>Waiting for events...</div>
        )}
        {reversed.map((ev, i) => (
          <div key={`${ev.timestamp}-${i}`} className="flex items-center gap-2">
            <span style={{ color: "var(--text-dim)" }}>{formatTime(ev.timestamp)}</span>
            <span style={{ color: KIND_COLORS[ev.kind] ?? "var(--text-secondary)" }}>
              {ev.kind.replace(/_/g, " ")}
            </span>
            <span style={{ color: "var(--text-dim)" }}>
              ({(ev.confidence * 100).toFixed(0)}%)
            </span>
            <span style={{ color: "var(--text-dim)" }}>→</span>
            <span style={{ color: "var(--status-info)" }}>
              {KIND_ACTIONS[ev.kind] ?? ev.kind}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
