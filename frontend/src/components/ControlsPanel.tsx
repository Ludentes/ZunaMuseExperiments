interface Props {
  isConnected: boolean;
  isRecording: boolean;
  duration: number;
  sendCommand: (cmd: Record<string, unknown>) => void;
}

export function ControlsPanel({ isConnected, isRecording, duration, sendCommand }: Props) {
  const formatTime = (sec: number) => {
    const m = Math.floor(sec / 60).toString().padStart(2, "0");
    const s = Math.floor(sec % 60).toString().padStart(2, "0");
    return `${m}:${s}`;
  };

  return (
    <div className="flex items-center gap-4 p-3" style={{ background: "var(--bg-panel)", borderTop: "1px solid var(--border)" }}>
      {/* Record controls */}
      <button
        onClick={() => sendCommand({ cmd: isRecording ? "stop_recording" : "start_recording" })}
        disabled={!isConnected}
        className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-mono uppercase tracking-wider border disabled:opacity-30"
        style={{
          background: isRecording ? "var(--status-bad)" : "transparent",
          borderColor: isRecording ? "var(--status-bad)" : "var(--border)",
          color: isRecording ? "#fff" : "var(--text-primary)",
        }}
      >
        {isRecording ? (
          <>
            <span className="inline-block w-2 h-2 bg-white rounded-full animate-pulse" />
            REC {formatTime(duration)}
          </>
        ) : (
          <>
            <span className="inline-block w-2 h-2 rounded-full border" style={{ borderColor: "var(--text-secondary)" }} />
            REC
          </>
        )}
      </button>

      <div className="h-6 w-px" style={{ background: "var(--border)" }} />

      {/* Connection indicator */}
      <div className="flex items-center gap-1.5 text-[11px] font-mono" style={{ color: "var(--text-dim)" }}>
        <span className="inline-block w-1.5 h-1.5 rounded-full" style={{
          background: isConnected ? "var(--status-good)" : "var(--status-bad)",
          boxShadow: isConnected ? "0 0 4px var(--status-good)" : "none"
        }} />
        {isConnected ? "ws://localhost:8765" : "disconnected"}
      </div>
    </div>
  );
}
