import React, { useCallback, useEffect, useRef, useState } from "react";

/** Protocol config per label */
interface Protocol {
  label: string;
  trialDuration: number;   // total trial length (seconds)
  cueAt: number;           // when to show "GO" cue (seconds from trial start)
  reps: number;            // number of trials
  restBetween: number;     // rest between trials (seconds)
  instruction: string;     // what to tell the user
  flickerHz?: number;      // SSVEP: flicker frequency in Hz (undefined = no flicker)
  metronomePeriod?: number; // metronome blink mode: fire a cue every N seconds during recording
}

const PROTOCOLS: Protocol[] = [
  { label: "baseline",     trialDuration: 60, cueAt: 0,  reps: 30, restBetween: 1, instruction: "Work normally — 30min continuous capture" },
  { label: "rest",         trialDuration: 5, cueAt: 0,   reps: 5,  restBetween: 2, instruction: "Relax, do nothing" },
  { label: "single_blink", trialDuration: 3, cueAt: 1,   reps: 20, restBetween: 2, instruction: "Blink once at the cue" },
  { label: "double_blink", trialDuration: 3, cueAt: 1,   reps: 20, restBetween: 2, instruction: "Double blink at the cue" },
  { label: "clench",       trialDuration: 3, cueAt: 1,   reps: 20, restBetween: 2, instruction: "Clench jaw briefly at the cue" },
  { label: "eyebrow_raise",trialDuration: 3, cueAt: 1,   reps: 20, restBetween: 2, instruction: "Raise both eyebrows at the cue" },
  { label: "eyebrow_furrow",trialDuration: 3, cueAt: 1,  reps: 20, restBetween: 2, instruction: "Furrow/scrunch eyebrows at the cue" },
  { label: "talk",         trialDuration: 5, cueAt: 0.5, reps: 10, restBetween: 2, instruction: "Say any word at the cue" },
  { label: "eyes_closed",  trialDuration: 30, cueAt: 0,  reps: 3,  restBetween: 5, instruction: "Close eyes, relax — keep still" },
  { label: "eyes_closed_tight", trialDuration: 30, cueAt: 0, reps: 5, restBetween: 5, instruction: "Close eyes TIGHTLY, squeeze — maximize alpha blocking" },
  { label: "eyes_open",    trialDuration: 30, cueAt: 0,  reps: 3,  restBetween: 5, instruction: "Eyes open, stare at screen — keep still" },
  // Experiment A: Engagement/attention
  { label: "meditation",   trialDuration: 60, cueAt: 0,  reps: 3,  restBetween: 10, instruction: "Close eyes, slow breathing, count breaths" },
  { label: "mental_math",  trialDuration: 60, cueAt: 0,  reps: 3,  restBetween: 10, instruction: "Count backwards from 1000 by 7s (eyes open)" },
  // Experiment B: SSVEP — visual flicker stimulus
  { label: "ssvep_7hz",    trialDuration: 15, cueAt: 1,  reps: 10, restBetween: 5, instruction: "Stare at the flickering pattern", flickerHz: 7.5 },
  { label: "ssvep_10hz",   trialDuration: 15, cueAt: 1,  reps: 10, restBetween: 5, instruction: "Stare at the flickering pattern", flickerHz: 10 },
  { label: "ssvep_6hz",    trialDuration: 15, cueAt: 1,  reps: 10, restBetween: 5, instruction: "Stare at the flickering pattern", flickerHz: 6 },
  { label: "ssvep_15hz",   trialDuration: 15, cueAt: 1,  reps: 10, restBetween: 5, instruction: "Stare at the flickering pattern", flickerHz: 15 },
  { label: "ssvep_none",   trialDuration: 15, cueAt: 1,  reps: 10, restBetween: 5, instruction: "Stare at the static pattern (control)", flickerHz: 0 },
  // Experiment C: Fz neurofeedback validation
  { label: "drowsy",       trialDuration: 60, cueAt: 0,  reps: 3,  restBetween: 10, instruction: "Eyes closed, let your mind wander — don't try to focus" },
  { label: "mentally_fatigued", trialDuration: 60, cueAt: 0, reps: 3, restBetween: 10, instruction: "Record as-is when feeling mentally tired — eyes open, normal posture" },
  // IMU / head gesture protocols
  { label: "nod_yes",       trialDuration: 3, cueAt: 1,   reps: 20, restBetween: 2, instruction: "Nod head YES once at the cue (chin down then up)" },
  { label: "nod_no",        trialDuration: 3, cueAt: 1,   reps: 20, restBetween: 2, instruction: "Shake head NO once at the cue (left-right)" },
  { label: "head_still",    trialDuration: 5, cueAt: 0,   reps: 10, restBetween: 2, instruction: "Keep head completely still — control baseline" },
  // Experiment D: Low-frequency photic driving validation
  { label: "flicker_3hz",  trialDuration: 15, cueAt: 1,  reps: 10, restBetween: 5, instruction: "Stare at the flickering pattern", flickerHz: 3 },
  { label: "flicker_4hz",  trialDuration: 15, cueAt: 1,  reps: 10, restBetween: 5, instruction: "Stare at the flickering pattern", flickerHz: 4 },  // 4Hz: 7.5 frames/half — slight jitter but still usable
  { label: "flicker_5hz",  trialDuration: 15, cueAt: 1,  reps: 10, restBetween: 5, instruction: "Stare at the flickering pattern", flickerHz: 5 },
  { label: "flicker_6hz",  trialDuration: 15, cueAt: 1,  reps: 10, restBetween: 5, instruction: "Stare at the flickering pattern", flickerHz: 6 },
  // Continuous session: metronome-prompted blinks for streaming detector evaluation
  // 32s × 3 trials. 2s warmup, then beats at t=2,5,8,...,29s = 10 blinks per trial.
  { label: "blink_continuous", trialDuration: 32, cueAt: 2, reps: 3, restBetween: 10, instruction: "Blink on each prompt (2s warmup)", metronomePeriod: 3 },
];

type SessionState =
  | { phase: "idle" }
  | { phase: "countdown"; secondsLeft: number }
  | { phase: "recording"; trialNum: number; elapsed: number; cued: boolean }
  | { phase: "rest"; trialNum: number; secondsLeft: number; canDiscard: boolean }
  | { phase: "done"; totalTrials: number };

interface Props {
  isConnected: boolean;
  sendCommand: (cmd: Record<string, unknown>) => void;
}

/**
 * SSVEP flicker overlay — renders a full-screen checkerboard that flickers at the target Hz.
 *
 * Timing: Uses absolute time reference (no drift accumulation).
 * The state at any moment is determined by Math.floor(elapsed / halfPeriodMs) % 2,
 * so frame drops and rAF jitter don't affect long-term frequency accuracy.
 *
 * Monitor constraint: Flicker frequency must divide evenly into half the refresh rate.
 * At 60Hz, clean frequencies are: 1, 2, 3, 4, 5, 6, 7.5, 10, 15, 30 Hz.
 * 12Hz CANNOT be displayed cleanly on 60Hz (needs 120Hz monitor).
 */
const SSVEPFlicker = React.memo(function SSVEPFlicker({ hz, active }: { hz: number; active: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const frameRef = useRef(0);

  useEffect(() => {
    if (!active || !canvasRef.current) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const isStatic = hz === 0;
    const halfPeriodMs = isStatic ? Infinity : 500 / hz;
    const startTime = performance.now();
    let lastDrawnState: boolean | null = null;

    // Measure refresh rate and warn about incompatible frequencies
    let measureCount = 0;
    const measureStart = performance.now();

    const drawCheckerboard = (on: boolean) => {
      const w = canvas.width;
      const h = canvas.height;
      const cellSize = 80;
      const white = on ? "#ffffff" : "#000000";
      const black = on ? "#000000" : "#ffffff";

      for (let y = 0; y < h; y += cellSize) {
        for (let x = 0; x < w; x += cellSize) {
          const col = Math.floor(x / cellSize);
          const row = Math.floor(y / cellSize);
          ctx.fillStyle = ((col + row) % 2) === 0 ? white : black;
          ctx.fillRect(x, y, cellSize, cellSize);
        }
      }

      // Red fixation cross at center
      ctx.fillStyle = "#ff0000";
      const cx = w / 2;
      const cy = h / 2;
      ctx.fillRect(cx - 15, cy - 2, 30, 4);
      ctx.fillRect(cx - 2, cy - 15, 4, 30);
    };

    const draw = () => {
      const now = performance.now();

      // Log refresh rate warning once after 10 frames (skip for static)
      if (!isStatic) {
        measureCount++;
        if (measureCount === 10) {
          const avgFrameMs = (now - measureStart) / measureCount;
          const refreshRate = Math.round(1000 / avgFrameMs);
          const framesPerHalfCycle = halfPeriodMs / avgFrameMs;
          const remainder = Math.abs(framesPerHalfCycle - Math.round(framesPerHalfCycle));
          if (remainder > 0.1) {
            console.warn(
              `SSVEP: ${hz}Hz cannot be displayed cleanly at ${refreshRate}Hz refresh. ` +
              `Frames per half-cycle: ${framesPerHalfCycle.toFixed(2)} (need near-integer).`
            );
          } else {
            console.info(`SSVEP: ${hz}Hz OK at ${refreshRate}Hz refresh (${framesPerHalfCycle.toFixed(1)} frames/half-cycle)`);
          }
        }
      }

      // Absolute time determines state — no drift accumulation
      const currentOn = isStatic ? true : (Math.floor((now - startTime) / halfPeriodMs) % 2) === 0;

      // Only redraw when state changes (saves GPU)
      if (currentOn !== lastDrawnState) {
        lastDrawnState = currentOn;
        drawCheckerboard(currentOn);
      }

      frameRef.current = requestAnimationFrame(draw);
    };

    // Size canvas to window (accounts for devicePixelRatio)
    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      canvas.width = window.innerWidth * dpr;
      canvas.height = window.innerHeight * dpr;
      canvas.style.width = window.innerWidth + "px";
      canvas.style.height = window.innerHeight + "px";
      ctx.scale(dpr, dpr);
      lastDrawnState = null; // force redraw after resize
    };
    resize();
    window.addEventListener("resize", resize);

    frameRef.current = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(frameRef.current);
      window.removeEventListener("resize", resize);
    };
  }, [hz, active]);

  if (!active) return null;

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 9999,
      display: "flex", alignItems: "center", justifyContent: "center",
    }}>
      <canvas ref={canvasRef} />
      <div style={{
        position: "absolute", bottom: 20, left: "50%", transform: "translateX(-50%)",
        background: "rgba(0,0,0,0.7)", color: "#fff", padding: "8px 16px",
        fontFamily: "monospace", fontSize: 12,
      }}>
        SSVEP {hz > 0 ? `${hz}Hz` : "static control"} — fixate on red cross — press ESC to abort
      </div>
    </div>
  );
});

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
  const [discardedCount, setDiscardedCount] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const trialStartRef = useRef(0);
  const abortRef = useRef(false);
  const lastBeatRef = useRef(-1);

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

        lastBeatRef.current = -1; // reset beat counter for each trial

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

          // Metronome beats (offset by cueAt so first beat fires after warmup)
          if (proto.metronomePeriod) {
            const metronomeElapsed = elapsed - proto.cueAt;
            if (metronomeElapsed >= 0) {
              const beat = Math.floor(metronomeElapsed / proto.metronomePeriod);
              if (beat > lastBeatRef.current) {
                lastBeatRef.current = beat;
                playBeep(660, 80);
              }
            }
          }

          // Trigger cue (for non-metronome protocols, or the initial start beep)
          if (!cued && elapsed >= proto.cueAt) {
            cued = true;
            if (!proto.metronomePeriod) playBeep(880, 100);
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
        setState({ phase: "rest", trialNum, secondsLeft: remaining, canDiscard: true });

        timerRef.current = setInterval(() => {
          if (abortRef.current) { cleanup(); resolve(); return; }
          remaining -= 0.1;
          if (remaining <= 0) {
            cleanup();
            resolve();
          } else {
            setState((prev) =>
              prev.phase === "rest"
                ? { ...prev, secondsLeft: remaining }
                : prev,
            );
          }
        }, 100);
      });
    },
    [cleanup],
  );

  // Discard previous trial
  const discardLastTrial = useCallback(() => {
    sendCommand({ cmd: "discard_last_recording" });
    setDiscardedCount((c) => c + 1);
    setState((prev) =>
      prev.phase === "rest" ? { ...prev, canDiscard: false } : prev,
    );
  }, [sendCommand]);

  // Run full session
  const startSession = useCallback(async () => {
    abortRef.current = false;
    setDiscardedCount(0);
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

  // SSVEP overlay state (includes static control where flickerHz === 0)
  const showFlicker = state.phase === "recording" && state.cued && protocol.flickerHz !== undefined;

  // ESC key to abort during SSVEP
  useEffect(() => {
    if (!showFlicker) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") stopSession();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [showFlicker, stopSession]);

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

          {/* Metronome mode: pulsing BLINK prompt every metronomePeriod seconds */}
          {protocol.metronomePeriod ? (() => {
            const period = protocol.metronomePeriod;
            const beatPhase = state.elapsed % period;
            const flashOn = beatPhase < 0.35; // flash for 350ms per beat
            const beatsLeft = Math.floor((protocol.trialDuration - state.elapsed) / period);
            return (
              <div
                className="flex flex-col items-center justify-center py-4 rounded transition-colors duration-75"
                style={{
                  background: flashOn ? "var(--accent)" : "rgba(255,255,255,0.03)",
                  border: flashOn ? "2px solid var(--accent)" : "2px solid var(--border)",
                }}
              >
                <span
                  className="text-2xl font-mono font-bold tracking-widest"
                  style={{ color: flashOn ? "var(--bg-base)" : "var(--text-dim)" }}
                >
                  {flashOn ? "BLINK ↓" : "..."}
                </span>
                <span className="text-[10px] font-mono mt-1" style={{ color: flashOn ? "var(--bg-base)" : "var(--text-dim)", opacity: 0.7 }}>
                  {beatsLeft > 0 ? `~${beatsLeft} more` : "finishing..."}
                </span>
              </div>
            );
          })() : (
            /* Normal cue indicator — hide for long trials after first 3 seconds */
            (!state.cued || state.elapsed < (protocol.cueAt + 3) || protocol.trialDuration <= 10) && (
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
            )
          )}
        </div>
      )}

      {state.phase === "rest" && (
        <div className="mb-3 flex items-center gap-3">
          <span className="text-sm font-mono" style={{ color: "var(--text-dim)" }}>
            Rest · trial {state.trialNum}/{protocol.reps} done · next in {Math.ceil(state.secondsLeft)}s
          </span>
          {state.canDiscard && (
            <button
              onClick={discardLastTrial}
              className="px-2.5 py-1 text-[11px] font-mono uppercase tracking-wider border transition-colors"
              style={{
                background: "transparent",
                borderColor: "var(--status-bad)",
                color: "var(--status-bad)",
              }}
            >
              DISCARD TRIAL
            </button>
          )}
        </div>
      )}

      {state.phase === "done" && (
        <div className="mb-3 flex items-center gap-3">
          <span className="text-sm font-mono" style={{ color: "var(--status-good)" }}>
            Done — {state.totalTrials - discardedCount} trials saved to recordings/{protocol.label}/
            {discardedCount > 0 && ` (${discardedCount} discarded)`}
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

      {/* SSVEP flicker overlay (including static control at hz=0) */}
      {protocol.flickerHz !== undefined && (
        <SSVEPFlicker hz={protocol.flickerHz} active={showFlicker} />
      )}
    </div>
  );
}
