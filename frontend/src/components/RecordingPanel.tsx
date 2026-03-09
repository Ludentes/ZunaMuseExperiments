import { useCallback, useEffect, useRef, useState } from "react";

/** Protocol config per label */
interface Protocol {
  label: string;
  trialDuration: number;  // total trial length (seconds)
  cueAt: number;          // when to show "GO" cue (seconds from trial start)
  reps: number;           // number of trials
  restBetween: number;    // rest between trials (seconds)
  instruction: string;    // what to tell the user
}

const PROTOCOLS: Protocol[] = [
  { label: "rest",         trialDuration: 5, cueAt: 0,   reps: 10, restBetween: 2, instruction: "Relax, do nothing" },
  { label: "single_blink", trialDuration: 3, cueAt: 1,   reps: 20, restBetween: 2, instruction: "Blink once at the cue" },
  { label: "double_blink", trialDuration: 3, cueAt: 1,   reps: 20, restBetween: 2, instruction: "Double blink at the cue" },
  { label: "triple_blink", trialDuration: 4, cueAt: 1,   reps: 20, restBetween: 2.5, instruction: "Triple blink at the cue" },
  { label: "clench",       trialDuration: 3, cueAt: 1,   reps: 20, restBetween: 2, instruction: "Clench jaw briefly at the cue" },
  { label: "talk",         trialDuration: 5, cueAt: 0.5, reps: 10, restBetween: 2, instruction: "Say any word at the cue" },
];

type SessionState =
  | { phase: "idle" }
  | { phase: "countdown"; secondsLeft: number }
  | { phase: "recording"; trialNum: number; elapsed: number; cued: boolean }
  | { phase: "rest"; trialNum: number; secondsLeft: number }
  | { phase: "done"; totalTrials: number };

interface Props {
  isConnected: boolean;
  sendCommand: (cmd: Record<string, unknown>) => void;
}

/** Play a short beep via Web Audio API */
function playBeep(freq: number = 880, durationMs: number = 100) {
  try {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.frequency.value = freq;
    gain.gain.value = 0.3;
    osc.start();
    osc.stop(ctx.currentTime + durationMs / 1000);
    setTimeout(() => ctx.close(), durationMs + 100);
  } catch {
    // Audio not available
  }
}

export function RecordingPanel({ isConnected, sendCommand }: Props) {
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [state, setState] = useState<SessionState>({ phase: "idle" });
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const trialStartRef = useRef(0);
  const abortRef = useRef(false);

  const protocol = PROTOCOLS[selectedIdx];

  const cleanup = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  // Stop session
  const stopSession = useCallback(() => {
    abortRef.current = true;
    cleanup();
    sendCommand({ cmd: "stop_recording" });
    setState({ phase: "idle" });
  }, [cleanup, sendCommand]);

  // Run one trial
  const runTrial = useCallback(
    (proto: Protocol, trialNum: number, sessionId: string): Promise<void> => {
      return new Promise((resolve) => {
        if (abortRef.current) { resolve(); return; }

        // Start recording on backend
        sendCommand({
          cmd: "start_recording",
          label: proto.label,
          trial_num: trialNum,
          cue_time_ms: Math.round(proto.cueAt * 1000),
          trial_duration_ms: Math.round(proto.trialDuration * 1000),
          session_id: sessionId,
        });

        trialStartRef.current = performance.now();
        let cued = false;

        setState({ phase: "recording", trialNum, elapsed: 0, cued: false });

        timerRef.current = setInterval(() => {
          if (abortRef.current) {
            cleanup();
            resolve();
            return;
          }

          const elapsed = (performance.now() - trialStartRef.current) / 1000;

          // Trigger cue
          if (!cued && elapsed >= proto.cueAt) {
            cued = true;
            playBeep(880, 100);
            setState({ phase: "recording", trialNum, elapsed, cued: true });
          } else {
            setState({ phase: "recording", trialNum, elapsed, cued });
          }

          // Trial complete
          if (elapsed >= proto.trialDuration) {
            cleanup();
            sendCommand({ cmd: "stop_recording" });
            resolve();
          }
        }, 50);
      });
    },
    [sendCommand, cleanup],
  );

  // Run rest period between trials
  const runRest = useCallback(
    (proto: Protocol, trialNum: number): Promise<void> => {
      return new Promise((resolve) => {
        if (abortRef.current) { resolve(); return; }

        let remaining = proto.restBetween;
        setState({ phase: "rest", trialNum, secondsLeft: remaining });

        timerRef.current = setInterval(() => {
          if (abortRef.current) { cleanup(); resolve(); return; }
          remaining -= 0.1;
          if (remaining <= 0) {
            cleanup();
            resolve();
          } else {
            setState({ phase: "rest", trialNum, secondsLeft: remaining });
          }
        }, 100);
      });
    },
    [cleanup],
  );

  // Run full session
  const startSession = useCallback(async () => {
    abortRef.current = false;
    const proto = PROTOCOLS[selectedIdx];
    // Generate a session ID so multiple runs of the same protocol don't collide
    const sessionId = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 15);

    // 3-2-1 countdown
    for (let i = 3; i > 0; i--) {
      if (abortRef.current) return;
      setState({ phase: "countdown", secondsLeft: i });
      playBeep(440, 80);
      await new Promise((r) => setTimeout(r, 1000));
    }

    for (let t = 1; t <= proto.reps; t++) {
      if (abortRef.current) return;
      await runTrial(proto, t, sessionId);
      if (t < proto.reps) {
        await runRest(proto, t);
      }
    }

    if (!abortRef.current) {
      setState({ phase: "done", totalTrials: proto.reps });
      playBeep(660, 300);
    }
  }, [selectedIdx, runTrial, runRest]);

  // Cleanup on unmount
  useEffect(() => cleanup, [cleanup]);

  const isActive = state.phase !== "idle" && state.phase !== "done";

  return (
    <div
      className="p-3"
      style={{
        background: "var(--bg-panel)",
        border: "1px solid var(--border)",
      }}
    >
      <div
        className="text-[12px] uppercase tracking-wider mb-3"
        style={{ color: "var(--text-secondary)", fontFamily: "var(--font-label)" }}
      >
        Cued Recording Protocol
      </div>

      {/* Protocol selector */}
      <div className="flex flex-wrap gap-1.5 mb-3">
        {PROTOCOLS.map((p, i) => (
          <button
            key={p.label}
            onClick={() => !isActive && setSelectedIdx(i)}
            disabled={isActive}
            className="px-2.5 py-1 text-[11px] font-mono uppercase tracking-wider border transition-colors disabled:opacity-50"
            style={{
              background: selectedIdx === i ? "var(--accent)" : "transparent",
              borderColor: selectedIdx === i ? "var(--accent)" : "var(--border)",
              color: selectedIdx === i ? "var(--bg-base)" : "var(--text-secondary)",
            }}
          >
            {p.label.replace("_", " ")}
          </button>
        ))}
      </div>

      {/* Protocol info */}
      {state.phase === "idle" && (
        <div className="mb-3 text-[11px] font-mono" style={{ color: "var(--text-dim)" }}>
          {protocol.reps} trials × {protocol.trialDuration}s
          {protocol.cueAt > 0 && <> · cue at {protocol.cueAt}s</>}
          {" · "}{protocol.instruction}
        </div>
      )}

      {/* Status display */}
      {state.phase === "countdown" && (
        <div className="mb-3 flex items-center gap-3">
          <span
            className="text-4xl font-mono font-bold"
            style={{ color: "var(--accent)" }}
          >
            {state.secondsLeft}
          </span>
          <span className="text-sm font-mono" style={{ color: "var(--text-secondary)" }}>
            Get ready...
          </span>
        </div>
      )}

      {state.phase === "recording" && (
        <div className="mb-3">
          <div className="flex items-center gap-3 mb-2">
            <span
              className="inline-block w-3 h-3 rounded-full animate-pulse"
              style={{ background: "var(--status-bad)" }}
            />
            <span className="text-sm font-mono" style={{ color: "var(--text-primary)" }}>
              Trial {state.trialNum}/{protocol.reps}
            </span>
            <span className="text-sm font-mono" style={{ color: "var(--text-dim)" }}>
              {state.elapsed.toFixed(1)}s / {protocol.trialDuration}s
            </span>
          </div>

          {/* CUE indicator */}
          <div
            className="flex items-center justify-center py-3 rounded transition-all duration-100"
            style={{
              background: state.cued ? "var(--accent)" : "rgba(255,255,255,0.03)",
              border: state.cued ? "2px solid var(--accent)" : "2px solid var(--border)",
            }}
          >
            <span
              className="text-2xl font-mono font-bold tracking-widest"
              style={{
                color: state.cued ? "var(--bg-base)" : "var(--text-dim)",
              }}
            >
              {state.cued ? protocol.instruction.toUpperCase() : "WAIT..."}
            </span>
          </div>
        </div>
      )}

      {state.phase === "rest" && (
        <div className="mb-3 flex items-center gap-3">
          <span className="text-sm font-mono" style={{ color: "var(--text-dim)" }}>
            Rest · trial {state.trialNum}/{protocol.reps} done · next in {Math.ceil(state.secondsLeft)}s
          </span>
        </div>
      )}

      {state.phase === "done" && (
        <div className="mb-3 flex items-center gap-3">
          <span className="text-sm font-mono" style={{ color: "var(--status-good)" }}>
            Done — {state.totalTrials} trials saved to recordings/{protocol.label}/
          </span>
        </div>
      )}

      {/* Controls */}
      <div className="flex items-center gap-3">
        {!isActive ? (
          <button
            onClick={startSession}
            disabled={!isConnected}
            className="flex items-center gap-2 px-4 py-2 text-[12px] font-mono uppercase tracking-wider border disabled:opacity-30 transition-colors"
            style={{
              background: "transparent",
              borderColor: "var(--border)",
              color: "var(--text-primary)",
            }}
          >
            <span
              className="inline-block w-2.5 h-2.5 rounded-full"
              style={{ background: "var(--status-bad)" }}
            />
            START SESSION
          </button>
        ) : (
          <button
            onClick={stopSession}
            className="flex items-center gap-2 px-4 py-2 text-[12px] font-mono uppercase tracking-wider border transition-colors"
            style={{
              background: "var(--status-bad)",
              borderColor: "var(--status-bad)",
              color: "#fff",
            }}
          >
            <span className="inline-block w-2.5 h-2.5 bg-white rounded-sm" />
            ABORT
          </button>
        )}

        {state.phase === "done" && (
          <button
            onClick={() => setState({ phase: "idle" })}
            className="px-3 py-2 text-[12px] font-mono uppercase tracking-wider border transition-colors"
            style={{
              background: "transparent",
              borderColor: "var(--border)",
              color: "var(--text-secondary)",
            }}
          >
            RESET
          </button>
        )}
      </div>
    </div>
  );
}
