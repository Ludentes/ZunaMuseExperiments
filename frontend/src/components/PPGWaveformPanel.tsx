import type { SensorBuffers } from "../hooks/useSensorStream";

interface Props {
  buffersRef: React.RefObject<SensorBuffers>;
}

export function PPGWaveformPanel({ buffersRef: _buffersRef }: Props) {
  // TODO: implement webgl-plot for PPG waveform (similar to EEGWaveformPanel but smaller)
  return (
    <div className="h-12" style={{ background: "var(--bg-panel)", border: "1px solid var(--border)" }}>
      <div className="text-[11px] uppercase tracking-wider p-1.5" style={{ color: "var(--text-secondary)", fontFamily: "var(--font-label)" }}>
        PPG IR · 64 Hz
      </div>
    </div>
  );
}
