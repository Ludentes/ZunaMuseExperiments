import { useState, useEffect, useRef, useCallback } from "react";

interface Props {
  sendCommand: (cmd: Record<string, unknown>) => void;
  isConnected: boolean;
  lastMessage?: MessageEvent | null;
}

export function ContinuousSession({ sendCommand, isConnected, lastMessage }: Props) {
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [markerCount, setMarkerCount] = useState(0);
  const startRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Listen for backend responses
  useEffect(() => {
    if (!lastMessage) return;
    try {
      const msg = JSON.parse(lastMessage.data as string);
      if (msg.type === "continuous_session_started") {
        setRecording(true);
        setMarkerCount(0);
        startRef.current = performance.now();
        timerRef.current = setInterval(() => {
          setElapsed((performance.now() - startRef.current) / 1000);
        }, 200);
      } else if (msg.type === "blink_marked") {
        setMarkerCount(msg.count);
      } else if (msg.type === "continuous_session_saved") {
        setRecording(false);
        if (timerRef.current) clearInterval(timerRef.current);
      }
    } catch {
      // binary frame
    }
  }, [lastMessage]);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const markBlink = useCallback(() => {
    if (recording) sendCommand({ cmd: "mark_blink" });
  }, [recording, sendCommand]);

  // Spacebar hotkey for marking blinks
  useEffect(() => {
    if (!recording) return;
    const handler = (e: KeyboardEvent) => {
      if (e.code === "Space" && !e.repeat) {
        e.preventDefault();
        markBlink();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [recording, markBlink]);

  if (!isConnected) return null;

  return (
    <div
      className="p-2"
      style={{ background: "var(--bg-panel)", border: "1px solid var(--border)" }}
    >
      <div
        className="text-[10px] font-mono uppercase tracking-wider mb-2"
        style={{ color: "var(--text-dim)" }}
      >
        Continuous Session
      </div>

      {!recording ? (
        <button
          onClick={() => sendCommand({ cmd: "start_continuous_session" })}
          className="w-full py-1.5 text-[11px] font-mono border"
          style={{
            color: "var(--status-good)",
            borderColor: "var(--status-good)",
            background: "rgba(56,232,112,0.08)",
            cursor: "pointer",
          }}
        >
          Start Recording
        </button>
      ) : (
        <div className="space-y-2">
          {/* Status bar */}
          <div className="flex items-center justify-between text-[11px] font-mono">
            <div className="flex items-center gap-2">
              <span
                className="inline-block w-2 h-2 rounded-full"
                style={{
                  background: "var(--status-bad)",
                  boxShadow: "0 0 6px var(--status-bad)",
                  animation: "pulse 1s ease-in-out infinite",
                }}
              />
              <span style={{ color: "var(--text-secondary)" }}>
                {elapsed.toFixed(0)}s
              </span>
            </div>
            <span style={{ color: "var(--text-dim)" }}>
              {markerCount} marks
            </span>
          </div>

          {/* Blink button */}
          <button
            onClick={markBlink}
            className="w-full py-3 text-sm font-mono border-2"
            style={{
              color: "var(--band-beta)",
              borderColor: "var(--band-beta)",
              background: "rgba(100,149,237,0.08)",
              cursor: "pointer",
            }}
          >
            BLINK [space]
          </button>

          {/* Stop button */}
          <button
            onClick={() => sendCommand({ cmd: "stop_continuous_session" })}
            className="w-full py-1 text-[10px] font-mono border"
            style={{
              color: "var(--text-dim)",
              borderColor: "var(--border)",
              background: "transparent",
              cursor: "pointer",
            }}
          >
            Stop & Save
          </button>
        </div>
      )}
    </div>
  );
}
