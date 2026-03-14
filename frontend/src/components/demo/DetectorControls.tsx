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

interface Props {
  sendCommand: (cmd: Record<string, unknown>) => void;
  isConnected: boolean;
  lastMessage?: MessageEvent | null;
}

export function DetectorControls({ sendCommand, isConnected, lastMessage }: Props) {
  const [thresholdSd, setThresholdSd] = useState(1.5);
  const [open, setOpen] = useState(false);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);

  // Listen for detector_snapshot messages from backend
  useEffect(() => {
    if (!lastMessage) return;
    try {
      const msg = JSON.parse(lastMessage.data as string);
      if (msg.type === "detector_snapshot") {
        setSnapshot(msg as Snapshot);
      }
    } catch {
      // binary frame, ignore
    }
  }, [lastMessage]);

  function apply(sd: number) {
    setThresholdSd(sd);
    sendCommand({ cmd: "set_blink_threshold", threshold_sd: sd });
  }

  function takeSnapshot() {
    sendCommand({ cmd: "snapshot_detector" });
  }

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
          {thresholdSd.toFixed(1)} SD {open ? "▲" : "▼"}
        </span>
      </button>

      {open && (
        <div className="mt-2 space-y-2">
          <input
            type="range"
            min={1.0}
            max={5.0}
            step={0.1}
            value={thresholdSd}
            onChange={(e) => apply(parseFloat(e.target.value))}
            className="w-full"
            style={{ accentColor: "var(--band-beta)" }}
          />
          <div
            className="flex justify-between text-[10px] font-mono"
            style={{ color: "var(--text-dim)" }}
          >
            <span>1.0 sensitive</span>
            <span>5.0 strict</span>
          </div>
          <div className="flex gap-1">
            {[1.5, 2.0, 2.5, 3.0].map((v) => (
              <button
                key={v}
                onClick={() => apply(v)}
                className="flex-1 py-0.5 text-[10px] font-mono border"
                style={{
                  color: thresholdSd === v ? "var(--status-good)" : "var(--text-dim)",
                  borderColor: thresholdSd === v ? "var(--status-good)" : "var(--border)",
                  background: thresholdSd === v ? "rgba(56,232,112,0.08)" : "transparent",
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
              📸
            </button>
          </div>

          {snapshot && (
            <div
              className="text-[10px] font-mono space-y-0.5 p-2"
              style={{ background: "var(--bg-input)", color: "var(--text-dim)" }}
            >
              <div style={{ color: "var(--text-secondary)" }}>Detector snapshot</div>
              <div>baseline {snapshot.baseline_median.toFixed(1)} µV  mad {snapshot.baseline_mad.toFixed(2)}</div>
              <div>robust_sd {snapshot.robust_sd.toFixed(2)}  thr_sd {snapshot.threshold_sd.toFixed(2)}</div>
              <div>adaptive_thr {snapshot.adaptive_thresh.toFixed(1)} µV</div>
              <div style={{ color: snapshot.threshold_uv > -9000 ? "var(--status-info)" : "var(--text-dim)" }}>
                thr_uv {snapshot.threshold_uv > -9000 ? `${snapshot.threshold_uv.toFixed(1)} µV` : "off"}
                {snapshot.threshold_uv > -9000 && ` → eff ${snapshot.effective_thresh.toFixed(1)} µV`}
              </div>
              <div>quality {(snapshot.frontal_quality * 100).toFixed(0)}%</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
