import type { SensorBuffers } from "../hooks/useSensorStream";

interface Props {
  heartRate?: number;
  spo2?: number;
  hrv?: number;
  buffersRef: React.RefObject<SensorBuffers>;
}

export function VitalsPanel({ heartRate, spo2, hrv }: Props) {
  const hrColor = "var(--status-bad)";
  const spo2Color = (spo2 ?? 0) > 95 ? "var(--status-good)" : (spo2 ?? 0) > 90 ? "var(--status-warn)" : "var(--status-bad)";

  return (
    <div className="p-3" style={{ background: "var(--bg-panel)", border: "1px solid var(--border)" }}>
      <div className="text-[12px] uppercase tracking-wider mb-3" style={{ color: "var(--text-secondary)", fontFamily: "var(--font-label)" }}>
        Vitals
      </div>
      <div className="grid grid-cols-3 gap-3">
        <div>
          <div className="text-[11px] uppercase" style={{ color: "var(--text-secondary)" }}>HR</div>
          <div className="flex items-baseline gap-1">
            <span className="animate-pulse" style={{ color: hrColor }}>♥</span>
            <span className="text-2xl font-mono" style={{ color: "var(--text-primary)" }}>{heartRate?.toFixed(0) ?? "--"}</span>
            <span className="text-[11px] font-mono" style={{ color: "var(--text-dim)" }}>bpm</span>
          </div>
        </div>
        <div>
          <div className="text-[11px] uppercase" style={{ color: "var(--text-secondary)" }}>SpO₂</div>
          <span className="text-xl font-mono" style={{ color: spo2Color }}>{spo2?.toFixed(1) ?? "--"}%</span>
        </div>
        <div>
          <div className="text-[11px] uppercase" style={{ color: "var(--text-secondary)" }}>HRV (RMSSD)</div>
          <span className="text-base font-mono" style={{ color: "var(--text-primary)" }}>{hrv?.toFixed(1) ?? "--"} ms</span>
        </div>
      </div>
    </div>
  );
}
