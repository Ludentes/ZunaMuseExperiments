import { useState, useEffect } from "react";

interface Snapshot {
  baseline_median: number;
  baseline_mad: number;
  robust_sd: number;
  threshold_sd: number;
  threshold_uv: number;
  adaptive_thresh: number;
  effective_thresh: number;
  baseline_samples: number;
  frontal_quality: number;
}

interface GuardStates {
  motion: boolean;
  bilateral: boolean;
  clench: boolean;
  speech: boolean;
  shape: boolean;
  template: boolean;
}

const GUARD_LABELS: Record<keyof GuardStates, string> = {
  motion: "Motion",
  bilateral: "Bilateral",
  clench: "Clench",
  speech: "Speech",
  shape: "Shape",
  template: "Template",
};

interface Props {
  sendCommand: (cmd: Record<string, unknown>) => void;
  isConnected: boolean;
  lastMessage?: MessageEvent | null;
}

// Sensitivity 1 = max FP (very permissive), 10 = max precision (very strict).
// Maps to threshold_sd and max_hf_ratio simultaneously.
function sensitivityToParams(s: number): { threshold_sd: number; max_hf_ratio: number } {
  // threshold_sd: 1.0 at s=1, 4.5 at s=10 (lower = detects weaker blinks)
  const threshold_sd = Math.round((1.0 + (s - 1) * (3.5 / 9)) * 10) / 10;
  // max_hf_ratio: 99 (disabled) at s=1, 3.5 (default) at s=5, 2.0 at s=10
  // piecewise: s=1→99, s=5→3.5, s=10→2.0
  let max_hf_ratio: number;
  if (s <= 5) {
    max_hf_ratio = 99 - (s - 1) / 4 * (99 - 3.5);
  } else {
    max_hf_ratio = 3.5 - (s - 5) / 5 * 1.5;
  }
  return { threshold_sd, max_hf_ratio: Math.round(max_hf_ratio * 10) / 10 };
}

const DEFAULT_SENSITIVITY = 5; // ~SD=2.6, hf_ratio=3.5 — matches backend defaults

const DEFAULT_GUARDS: GuardStates = {
  motion: true,
  bilateral: true,
  clench: true,
  speech: true,
  shape: true,
  template: true,
};

export function DetectorControls({ sendCommand, isConnected, lastMessage }: Props) {
  const [sensitivity, setSensitivity] = useState(DEFAULT_SENSITIVITY);
  const [open, setOpen] = useState(false);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [guards, setGuards] = useState<GuardStates>(DEFAULT_GUARDS);
  const [guardsOpen, setGuardsOpen] = useState(false);

  // Listen for detector_snapshot and guard_states messages
  useEffect(() => {
    if (!lastMessage) return;
    try {
      const msg = JSON.parse(lastMessage.data as string);
      if (msg.type === "detector_snapshot") {
        setSnapshot(msg as Snapshot);
      } else if (msg.type === "guard_states") {
        setGuards({
          motion: msg.motion ?? true,
          bilateral: msg.bilateral ?? true,
          clench: msg.clench ?? true,
          speech: msg.speech ?? true,
          shape: msg.shape ?? true,
          template: msg.template ?? true,
        });
      }
    } catch {
      // binary frame, ignore
    }
  }, [lastMessage]);

  // Fetch guard states on mount
  useEffect(() => {
    if (isConnected) {
      sendCommand({ cmd: "get_guards" });
    }
  }, [isConnected, sendCommand]);

  function apply(s: number) {
    setSensitivity(s);
    const { threshold_sd, max_hf_ratio } = sensitivityToParams(s);
    sendCommand({ cmd: "set_blink_threshold", threshold_sd, max_hf_ratio });
  }

  function toggleGuard(name: keyof GuardStates) {
    const newState = { ...guards, [name]: !guards[name] };
    setGuards(newState);
    sendCommand({ cmd: "set_guards", guards: newState });
  }

  function takeSnapshot() {
    sendCommand({ cmd: "snapshot_detector" });
  }

  const { threshold_sd, max_hf_ratio } = sensitivityToParams(sensitivity);
  const guardLabel = max_hf_ratio >= 50 ? "off" : `${max_hf_ratio.toFixed(1)}x`;
  const disabledCount = Object.values(guards).filter((v) => !v).length;

  if (!isConnected) return null;

  return (
    <div
      className="p-2"
      style={{ background: "var(--bg-panel)", border: "1px solid var(--border)" }}
    >
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between text-[10px] font-mono uppercase tracking-wider"
        style={{ color: "var(--text-dim)", background: "transparent", cursor: "pointer" }}
      >
        <span>Blink Sensitivity</span>
        <span style={{ color: "var(--text-secondary)" }}>
          {sensitivity}/10 {open ? "\u25B2" : "\u25BC"}
        </span>
      </button>

      {open && (
        <div className="mt-2 space-y-2">
          <input
            type="range"
            min={1}
            max={10}
            step={1}
            value={sensitivity}
            onChange={(e) => apply(parseInt(e.target.value))}
            className="w-full"
            style={{ accentColor: "var(--band-beta)" }}
          />
          <div
            className="flex justify-between text-[10px] font-mono"
            style={{ color: "var(--text-dim)" }}
          >
            <span>1 max FP</span>
            <span style={{ color: "var(--text-secondary)" }}>
              SD={threshold_sd} guard={guardLabel}
            </span>
            <span>10 strict</span>
          </div>

          <div className="flex gap-1">
            {[1, 3, 5, 7, 10].map((v) => (
              <button
                key={v}
                onClick={() => apply(v)}
                className="flex-1 py-0.5 text-[10px] font-mono border"
                style={{
                  color: sensitivity === v ? "var(--status-good)" : "var(--text-dim)",
                  borderColor: sensitivity === v ? "var(--status-good)" : "var(--border)",
                  background: sensitivity === v ? "rgba(56,232,112,0.08)" : "transparent",
                  cursor: "pointer",
                }}
              >
                {v}
              </button>
            ))}
            <button
              onClick={takeSnapshot}
              className="flex-1 py-0.5 text-[10px] font-mono border"
              style={{
                color: "var(--text-secondary)",
                borderColor: "var(--border)",
                background: "transparent",
                cursor: "pointer",
              }}
            >
              S
            </button>
          </div>

          {/* Guard toggles */}
          <button
            onClick={() => setGuardsOpen((o) => !o)}
            className="w-full flex items-center justify-between text-[10px] font-mono"
            style={{ color: "var(--text-dim)", background: "transparent", cursor: "pointer" }}
          >
            <span>Guards</span>
            <span style={{ color: disabledCount > 0 ? "var(--status-warn)" : "var(--text-dim)" }}>
              {disabledCount > 0 ? `${disabledCount} off` : "all on"} {guardsOpen ? "\u25B2" : "\u25BC"}
            </span>
          </button>

          {guardsOpen && (
            <div className="grid grid-cols-3 gap-1">
              {(Object.keys(GUARD_LABELS) as (keyof GuardStates)[]).map((name) => (
                <button
                  key={name}
                  onClick={() => toggleGuard(name)}
                  className="py-0.5 text-[10px] font-mono border"
                  style={{
                    color: guards[name] ? "var(--status-good)" : "var(--status-bad)",
                    borderColor: guards[name] ? "var(--status-good)" : "var(--status-bad)",
                    background: guards[name] ? "rgba(56,232,112,0.08)" : "rgba(232,56,56,0.08)",
                    cursor: "pointer",
                  }}
                >
                  {GUARD_LABELS[name]}
                </button>
              ))}
            </div>
          )}

          {snapshot && (
            <div
              className="text-[10px] font-mono space-y-0.5 p-2"
              style={{ background: "var(--bg-input)", color: "var(--text-dim)" }}
            >
              <div style={{ color: "var(--text-secondary)" }}>Detector snapshot</div>
              <div>baseline {snapshot.baseline_median.toFixed(1)} uV  mad {snapshot.baseline_mad.toFixed(2)}</div>
              <div>robust_sd {snapshot.robust_sd.toFixed(2)}  thr_sd {snapshot.threshold_sd.toFixed(2)}</div>
              <div>adaptive_thr {snapshot.adaptive_thresh.toFixed(1)} uV</div>
              <div style={{ color: snapshot.threshold_uv > -9000 ? "var(--status-info)" : "var(--text-dim)" }}>
                thr_uv {snapshot.threshold_uv > -9000 ? `${snapshot.threshold_uv.toFixed(1)} uV` : "off"}
                {snapshot.threshold_uv > -9000 && ` -> eff ${snapshot.effective_thresh.toFixed(1)} uV`}
              </div>
              <div>quality {(snapshot.frontal_quality * 100).toFixed(0)}%</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
