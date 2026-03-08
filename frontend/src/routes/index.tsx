import { createFileRoute } from "@tanstack/react-router";
import { useSensorStream } from "../hooks/useSensorStream";
import { useMetrics } from "../hooks/useMetrics";
import { EEGWaveformPanel } from "../components/EEGWaveformPanel";
import { FitTool } from "../components/FitTool";
import { BrainMetrics } from "../components/BrainMetrics";
import { VitalsPanel } from "../components/VitalsPanel";
import { MotionPanel } from "../components/MotionPanel";
import { ControlsPanel } from "../components/ControlsPanel";

export const Route = createFileRoute("/")({
  component: Dashboard,
});

function Dashboard() {
  const { buffers, metricsRef, isConnected, sendCommand } = useSensorStream();
  const metrics = useMetrics(metricsRef);

  return (
    <div className="min-h-screen p-2 space-y-2" style={{ background: "var(--bg-base)", color: "var(--text-primary)" }}>
      {/* Top bar */}
      <div className="flex items-center justify-between h-8 px-2">
        <span className="text-sm font-mono" style={{ color: "var(--text-dim)" }}>CORTEX</span>
        <div className="flex items-center gap-2 text-[11px] font-mono" style={{ color: "var(--text-dim)" }}>
          <span className="inline-block w-2 h-2 rounded-full" style={{
            background: isConnected ? "var(--status-good)" : "var(--status-bad)",
            boxShadow: isConnected ? "0 0 6px var(--status-good)" : "none",
            animation: isConnected ? "pulse 2s infinite" : "none"
          }} />
          ws://localhost:8765
        </div>
      </div>

      {/* Fit Tool */}
      <FitTool
        signalQuality={metrics?.eeg?.signal_quality}
        fitStatus={metrics?.eeg?.fit_status}
        motionArtifact={metrics?.imu?.motion_artifact}
        jawClench={metrics?.imu?.jaw_clench}
      />

      {/* EEG Waveforms */}
      <EEGWaveformPanel buffersRef={buffers} />

      {/* Bottom panels: metrics + vitals/motion side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2" style={{ gap: "var(--gap)" }}>
        <BrainMetrics
          bandPowers={metrics?.eeg?.band_powers}
          thetaBetaRatio={metrics?.eeg?.theta_beta_ratio}
          faa={metrics?.eeg?.frontal_alpha_asymmetry}
        />
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--gap)" }}>
          <VitalsPanel
            heartRate={metrics?.ppg?.heart_rate_bpm}
            spo2={metrics?.ppg?.spo2_percent}
            hrv={metrics?.ppg?.hrv_rmssd_ms}
            buffersRef={buffers}
          />
          <MotionPanel
            headMovement={metrics?.imu?.head_movement}
            headPose={metrics?.imu?.head_pose}
            motionArtifact={metrics?.imu?.motion_artifact}
            jawClench={metrics?.imu?.jaw_clench}
          />
        </div>
      </div>

      {/* Controls */}
      <ControlsPanel
        isConnected={isConnected}
        isRecording={metrics?.session?.recording ?? false}
        duration={metrics?.session?.duration_sec ?? 0}
        sendCommand={sendCommand}
      />
    </div>
  );
}
