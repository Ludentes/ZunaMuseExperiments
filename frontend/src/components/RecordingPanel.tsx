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
  pvt?: boolean;           // PVT-B mode: show reaction time task during recording
}

const PROTOCOLS: Protocol[] = [
  { label: "baseline",     trialDuration: 60, cueAt: 0,  reps: 30, restBetween: 1, instruction: "Work normally — 30min continuous capture" },
  { label: "rest",         trialDuration: 5, cueAt: 0,   reps: 5,  restBetween: 2, instruction: "Relax, do nothing" },
  { label: "single_blink", trialDuration: 5, cueAt: 2,   reps: 20, restBetween: 2, instruction: "Blink once at the cue" },
  { label: "double_blink", trialDuration: 5, cueAt: 2,   reps: 20, restBetween: 2, instruction: "Double blink at the cue" },
  { label: "clench",       trialDuration: 5, cueAt: 2,   reps: 20, restBetween: 2, instruction: "Clench jaw briefly at the cue" },
  { label: "eyebrow_raise",trialDuration: 5, cueAt: 2,   reps: 20, restBetween: 2, instruction: "Raise both eyebrows at the cue" },
  { label: "eyebrow_furrow",trialDuration: 5, cueAt: 2,  reps: 20, restBetween: 2, instruction: "Furrow/scrunch eyebrows at the cue" },
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
  { label: "nod_yes",       trialDuration: 5, cueAt: 2,   reps: 20, restBetween: 2, instruction: "Nod head YES once at the cue (chin down then up)" },
  { label: "nod_no",        trialDuration: 5, cueAt: 2,   reps: 20, restBetween: 2, instruction: "Shake head NO once at the cue (left-right)" },
  { label: "head_still",    trialDuration: 5, cueAt: 0,   reps: 10, restBetween: 2, instruction: "Keep head completely still — control baseline" },
  // Experiment D: Low-frequency photic driving validation
  { label: "flicker_3hz",  trialDuration: 15, cueAt: 1,  reps: 10, restBetween: 5, instruction: "Stare at the flickering pattern", flickerHz: 3 },
  { label: "flicker_4hz",  trialDuration: 15, cueAt: 1,  reps: 10, restBetween: 5, instruction: "Stare at the flickering pattern", flickerHz: 4 },  // 4Hz: 7.5 frames/half — slight jitter but still usable
  { label: "flicker_5hz",  trialDuration: 15, cueAt: 1,  reps: 10, restBetween: 5, instruction: "Stare at the flickering pattern", flickerHz: 5 },
  { label: "flicker_6hz",  trialDuration: 15, cueAt: 1,  reps: 10, restBetween: 5, instruction: "Stare at the flickering pattern", flickerHz: 6 },
  // Continuous session: metronome-prompted blinks for streaming detector evaluation
  // 32s × 3 trials. 2s warmup, then beats at t=2,5,8,...,29s = 10 blinks per trial.
  { label: "blink_continuous", trialDuration: 32, cueAt: 2, reps: 3, restBetween: 10, instruction: "Blink on each prompt (2s warmup)", metronomePeriod: 3 },
  // Brain Fry: standalone 3-min PVT-B with EEG recording.
  // Record a few when fresh and a few when tired to build fatigue baseline.
  { label: "pvt_brainfry", trialDuration: 180, cueAt: 0, reps: 1, restBetween: 1, instruction: "Tap SPACE as fast as possible when you see the red circle", pvt: true },
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

/** Play a loud ascending alarm to get user's attention from another tab/window.
 * Three ascending tone triplets: 440→660→880, repeated 3 times with gaps. */
function playAlertSound() {
  try {
    const ctx = getAudioCtx();
    if (ctx.state === "suspended") ctx.resume();
    const gain = ctx.createGain();
    gain.connect(ctx.destination);
    gain.gain.value = 0.6; // louder than normal beeps

    const tones = [440, 660, 880, 440, 660, 880, 440, 660, 880];
    const durations = [0.15, 0.15, 0.25, 0.15, 0.15, 0.25, 0.15, 0.15, 0.4];
    let t = ctx.currentTime;
    for (let i = 0; i < tones.length; i++) {
      const osc = ctx.createOscillator();
      osc.connect(gain);
      osc.frequency.value = tones[i];
      osc.start(t);
      osc.stop(t + durations[i]);
      t += durations[i] + 0.05;
    }
  } catch (e) { console.warn("playAlertSound failed:", e); }
}

/** PVT result for a single stimulus */
interface PVTResponse {
  interval_ms: number;  // how long user waited before stimulus
  rt_ms: number;        // reaction time (-1 = lapse/timeout, -2 = false start)
  timestamp: number;    // performance.now() of stimulus
}

/** PVT-B (Brief Psychomotor Vigilance Task) overlay.
 * Shows fixation cross, then after random 2-10s interval shows a red target.
 * User presses Space/clicks as fast as possible. Measures reaction time.
 * Runs for `durationS` seconds, then calls `onComplete` with results.
 * Also writes each response to `sharedResultsRef` so the parent can read
 * accumulated results even if the overlay hasn't finished yet. */
const PVTOverlay = React.memo(function PVTOverlay({
  durationS,
  active,
  onComplete,
  sharedResultsRef,
}: {
  durationS: number;
  active: boolean;
  onComplete: (results: PVTResponse[]) => void;
  sharedResultsRef: React.MutableRefObject<PVTResponse[] | null>;
}) {
  const [pvtState, setPvtState] = useState<
    | { phase: "waiting"; countdown: number }
    | { phase: "stimulus"; startedAt: number }
    | { phase: "feedback"; rt: number }
    | { phase: "too_early" }
    | { phase: "summary"; results: PVTResponse[] }
  >({ phase: "waiting", countdown: 0 });

  const resultsRef = useRef<PVTResponse[]>([]);
  const stimulusTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const feedbackTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sessionStartRef = useRef(0);
  const stimulusStartRef = useRef(0);
  const currentIntervalRef = useRef(0);
  const activeRef = useRef(active);
  const elapsedRef = useRef(0);
  const elapsedTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  activeRef.current = active;

  /** Push a response and sync to parent ref */
  const pushResult = useCallback((r: PVTResponse) => {
    resultsRef.current.push(r);
    sharedResultsRef.current = [...resultsRef.current];
  }, [sharedResultsRef]);

  const clearTimers = useCallback(() => {
    if (stimulusTimerRef.current) { clearTimeout(stimulusTimerRef.current); stimulusTimerRef.current = null; }
    if (feedbackTimerRef.current) { clearTimeout(feedbackTimerRef.current); feedbackTimerRef.current = null; }
    if (elapsedTimerRef.current) { clearInterval(elapsedTimerRef.current); elapsedTimerRef.current = null; }
  }, []);

  const scheduleNextStimulus = useCallback(() => {
    if (!activeRef.current) return;
    const remaining = durationS - (performance.now() - sessionStartRef.current) / 1000;
    if (remaining < 2) {
      // Session ending — show summary
      const results = resultsRef.current;
      setPvtState({ phase: "summary", results });
      onComplete(results);
      return;
    }
    // Random interval 2-10s (clamp to remaining time)
    const interval = Math.min(2000 + Math.random() * 8000, remaining * 1000 - 500);
    currentIntervalRef.current = interval;
    setPvtState({ phase: "waiting", countdown: Math.ceil(interval / 1000) });

    stimulusTimerRef.current = setTimeout(() => {
      if (!activeRef.current) return;
      stimulusStartRef.current = performance.now();
      setPvtState({ phase: "stimulus", startedAt: stimulusStartRef.current });
      playBeep(1200, 50); // short high pip when stimulus appears

      // Auto-timeout after 3s (lapse)
      feedbackTimerRef.current = setTimeout(() => {
        if (!activeRef.current) return;
        pushResult({
          interval_ms: currentIntervalRef.current,
          rt_ms: -1, // lapse
          timestamp: stimulusStartRef.current,
        });
        setPvtState({ phase: "feedback", rt: -1 });
        feedbackTimerRef.current = setTimeout(() => scheduleNextStimulus(), 800);
      }, 3000);
    }, interval);
  }, [durationS, onComplete, pushResult]);

  // Start PVT session
  useEffect(() => {
    if (!active) {
      clearTimers();
      return;
    }
    resultsRef.current = [];
    sharedResultsRef.current = [];
    sessionStartRef.current = performance.now();
    elapsedRef.current = 0;
    // Update elapsed every 500ms for display
    elapsedTimerRef.current = setInterval(() => {
      elapsedRef.current = (performance.now() - sessionStartRef.current) / 1000;
    }, 500);
    scheduleNextStimulus();
    return clearTimers;
  }, [active, scheduleNextStimulus, clearTimers]);

  // Handle spacebar/click response
  useEffect(() => {
    if (!active) return;
    const handler = (e: KeyboardEvent | MouseEvent) => {
      if (e instanceof KeyboardEvent && e.key !== " ") return;
      if (e instanceof KeyboardEvent) e.preventDefault();

      if (pvtState.phase === "stimulus") {
        // Valid response
        const rt = performance.now() - stimulusStartRef.current;
        if (feedbackTimerRef.current) { clearTimeout(feedbackTimerRef.current); feedbackTimerRef.current = null; }
        pushResult({
          interval_ms: currentIntervalRef.current,
          rt_ms: rt,
          timestamp: stimulusStartRef.current,
        });
        setPvtState({ phase: "feedback", rt });
        feedbackTimerRef.current = setTimeout(() => scheduleNextStimulus(), 800);
      } else if (pvtState.phase === "waiting") {
        // False start
        if (stimulusTimerRef.current) { clearTimeout(stimulusTimerRef.current); stimulusTimerRef.current = null; }
        pushResult({
          interval_ms: currentIntervalRef.current,
          rt_ms: -2, // false start
          timestamp: performance.now(),
        });
        setPvtState({ phase: "too_early" });
        feedbackTimerRef.current = setTimeout(() => scheduleNextStimulus(), 1200);
      }
    };
    window.addEventListener("keydown", handler);
    window.addEventListener("mousedown", handler);
    return () => {
      window.removeEventListener("keydown", handler);
      window.removeEventListener("mousedown", handler);
    };
  }, [active, pvtState.phase, scheduleNextStimulus]);

  if (!active) return null;

  const elapsed = (performance.now() - sessionStartRef.current) / 1000;
  const remaining = Math.max(0, durationS - elapsed);
  const validRTs = resultsRef.current.filter(r => r.rt_ms > 0);
  const lapses = resultsRef.current.filter(r => r.rt_ms === -1).length;
  const falseStarts = resultsRef.current.filter(r => r.rt_ms === -2).length;

  return (
    <div
      style={{
        position: "fixed", inset: 0, zIndex: 9999,
        background: "#111", display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        fontFamily: "monospace", color: "#fff",
        cursor: pvtState.phase === "stimulus" ? "pointer" : "default",
      }}
      onClick={() => {
        // Forward clicks to mousedown handler
      }}
    >
      {/* Timer bar */}
      <div style={{
        position: "absolute", top: 0, left: 0, right: 0, height: 4,
        background: "rgba(255,255,255,0.1)",
      }}>
        <div style={{
          height: "100%", background: "#4ade80",
          width: `${(1 - remaining / durationS) * 100}%`,
          transition: "width 0.5s linear",
        }} />
      </div>

      {/* Stats bar */}
      <div style={{
        position: "absolute", top: 12, left: 20, right: 20,
        display: "flex", justifyContent: "space-between",
        fontSize: 12, color: "rgba(255,255,255,0.4)",
      }}>
        <span>{Math.floor(remaining / 60)}:{String(Math.floor(remaining % 60)).padStart(2, "0")} remaining</span>
        <span>{validRTs.length} responses · {lapses} lapses · {falseStarts} false starts</span>
      </div>

      {/* Main content */}
      {pvtState.phase === "waiting" && (
        <div style={{ fontSize: 72, color: "rgba(255,255,255,0.15)", userSelect: "none" }}>+</div>
      )}

      {pvtState.phase === "stimulus" && (
        <div style={{
          width: 120, height: 120, borderRadius: "50%",
          background: "#ef4444", boxShadow: "0 0 60px rgba(239,68,68,0.5)",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 14, color: "#fff", fontWeight: "bold",
          cursor: "pointer",
        }}>
          TAP!
        </div>
      )}

      {pvtState.phase === "feedback" && (
        <div style={{ textAlign: "center" }}>
          {pvtState.rt > 0 ? (
            <>
              <div style={{
                fontSize: 64, fontWeight: "bold",
                color: pvtState.rt < 300 ? "#4ade80" : pvtState.rt < 500 ? "#facc15" : "#ef4444",
              }}>
                {Math.round(pvtState.rt)} ms
              </div>
              <div style={{ fontSize: 14, color: "rgba(255,255,255,0.4)", marginTop: 8 }}>
                {pvtState.rt < 250 ? "Excellent" : pvtState.rt < 350 ? "Good" : pvtState.rt < 500 ? "Slow" : "Very slow"}
              </div>
            </>
          ) : (
            <div style={{ fontSize: 32, color: "#ef4444" }}>LAPSE (no response)</div>
          )}
        </div>
      )}

      {pvtState.phase === "too_early" && (
        <div style={{ fontSize: 24, color: "#facc15", textAlign: "center" }}>
          TOO EARLY!<br />
          <span style={{ fontSize: 14, color: "rgba(255,255,255,0.4)" }}>Wait for the red circle</span>
        </div>
      )}

      {pvtState.phase === "summary" && (() => {
        const rts = pvtState.results.filter(r => r.rt_ms > 0).map(r => r.rt_ms);
        const meanRT = rts.length > 0 ? rts.reduce((a, b) => a + b, 0) / rts.length : 0;
        const medianRT = rts.length > 0 ? [...rts].sort((a, b) => a - b)[Math.floor(rts.length / 2)] : 0;
        const fastestRT = rts.length > 0 ? Math.min(...rts) : 0;
        const totalLapses = pvtState.results.filter(r => r.rt_ms === -1).length;
        const totalFalse = pvtState.results.filter(r => r.rt_ms === -2).length;
        return (
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: 18, color: "rgba(255,255,255,0.5)", marginBottom: 16 }}>PVT-B COMPLETE</div>
            <div style={{ fontSize: 48, fontWeight: "bold", color: "#4ade80" }}>{Math.round(medianRT)} ms</div>
            <div style={{ fontSize: 14, color: "rgba(255,255,255,0.4)", marginTop: 4 }}>median reaction time</div>
            <div style={{ display: "flex", gap: 32, marginTop: 24, fontSize: 14 }}>
              <div><span style={{ color: "#4ade80" }}>{Math.round(meanRT)}</span> mean</div>
              <div><span style={{ color: "#4ade80" }}>{Math.round(fastestRT)}</span> fastest</div>
              <div><span style={{ color: totalLapses > 0 ? "#ef4444" : "#4ade80" }}>{totalLapses}</span> lapses</div>
              <div><span style={{ color: totalFalse > 0 ? "#facc15" : "#4ade80" }}>{totalFalse}</span> false starts</div>
              <div><span style={{ color: "#fff" }}>{rts.length}</span> trials</div>
            </div>
          </div>
        );
      })()}

      {/* Instructions */}
      <div style={{
        position: "absolute", bottom: 20, left: "50%", transform: "translateX(-50%)",
        fontSize: 12, color: "rgba(255,255,255,0.3)", textAlign: "center",
      }}>
        Press SPACE or click when you see the red circle — press ESC to abort
      </div>
    </div>
  );
});

/** Shared AudioContext — reused across all beeps to avoid browser context limits */
let sharedAudioCtx: AudioContext | null = null;
function getAudioCtx(): AudioContext {
  if (!sharedAudioCtx || sharedAudioCtx.state === "closed") {
    sharedAudioCtx = new AudioContext();
  }
  return sharedAudioCtx;
}

/** Play a short beep via Web Audio API */
function playBeep(freq: number = 880, durationMs: number = 100) {
  try {
    const ctx = getAudioCtx();
    if (ctx.state === "suspended") ctx.resume();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.frequency.value = freq;
    gain.gain.value = 0.3;
    osc.start();
    osc.stop(ctx.currentTime + durationMs / 1000);
  } catch (e) {
    console.warn("playBeep failed:", e);
  }
}

export function RecordingPanel({ isConnected, sendCommand }: Props) {
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [state, setState] = useState<SessionState>({ phase: "idle" });
  const [discardedCount, setDiscardedCount] = useState(0);
  const [pvtActive, setPvtActive] = useState(false);
  const [pvtNote, setPvtNote] = useState("");
  const pvtNoteRef = useRef("");
  const pvtResultsRef = useRef<PVTResponse[] | null>(null);
  const pvtResolveRef = useRef<(() => void) | null>(null);
  const skipRestRef = useRef(false);
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

  // Handle PVT completion
  const handlePvtComplete = useCallback((results: PVTResponse[]) => {
    pvtResultsRef.current = results;
    // PVT overlay done — resolve will happen when timer finishes
  }, []);

  // Run one trial
  const runTrial = useCallback(
    (proto: Protocol, trialNum: number, sessionId: string): Promise<void> => {
      return new Promise((resolve) => {
        if (abortRef.current) { resolve(); return; }

        lastBeatRef.current = -1; // reset beat counter for each trial
        pvtResultsRef.current = null;

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

        // PVT mode: activate overlay
        if (proto.pvt) {
          setPvtActive(true);
          pvtResolveRef.current = resolve;
        }

        setState({ phase: "recording", trialNum, elapsed: 0, cued: false });

        timerRef.current = setInterval(() => {
          if (abortRef.current) {
            cleanup();
            if (proto.pvt) setPvtActive(false);
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
            if (!proto.metronomePeriod && !proto.pvt) playBeep(880, 100);
            setState({ phase: "recording", trialNum, elapsed, cued: true });
          } else {
            setState({ phase: "recording", trialNum, elapsed, cued });
          }

          // Trial complete
          if (elapsed >= proto.trialDuration) {
            cleanup();
            sendCommand({ cmd: "stop_recording" });
            if (proto.pvt) {
              setPvtActive(false);
              // Send PVT results to backend (sharedResultsRef is populated incrementally)
              const responses = pvtResultsRef.current ?? [];
              if (responses.length > 0) {
                const rts = responses.filter(r => r.rt_ms > 0).map(r => r.rt_ms);
                sendCommand({
                  cmd: "save_pvt_results",
                  label: proto.label,
                  session_id: sessionId,
                  trial_num: trialNum,
                  results: {
                    responses,
                    mean_rt: rts.length > 0 ? rts.reduce((a, b) => a + b, 0) / rts.length : 0,
                    median_rt: rts.length > 0 ? [...rts].sort((a, b) => a - b)[Math.floor(rts.length / 2)] : 0,
                    fastest_rt: rts.length > 0 ? Math.min(...rts) : 0,
                    lapses: responses.filter(r => r.rt_ms === -1).length,
                    false_starts: responses.filter(r => r.rt_ms === -2).length,
                    n_valid: rts.length,
                    ...(pvtNoteRef.current.trim() && { note: pvtNoteRef.current.trim() }),
                  },
                });
              }
            }
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
        skipRestRef.current = false;

        let remaining = proto.restBetween;
        setState({ phase: "rest", trialNum, secondsLeft: remaining, canDiscard: true });

        timerRef.current = setInterval(() => {
          if (abortRef.current || skipRestRef.current) { cleanup(); resolve(); return; }
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

    for (let t = 1; t <= proto.reps; t++) {
      if (abortRef.current) return;

      // PVT mode: play alert sound before each round (except first which starts immediately)
      if (proto.pvt && t > 1) {
        playAlertSound();
        // Wait 3s for user to switch to browser
        for (let i = 3; i > 0; i--) {
          if (abortRef.current) return;
          setState({ phase: "countdown", secondsLeft: i });
          await new Promise((r) => setTimeout(r, 1000));
        }
      } else {
        // Normal 3-2-1 countdown (only for first trial, or non-PVT protocols)
        if (t === 1) {
          for (let i = 3; i > 0; i--) {
            if (abortRef.current) return;
            setState({ phase: "countdown", secondsLeft: i });
            playBeep(440, 80);
            await new Promise((r) => setTimeout(r, 1000));
          }
        }
      }

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

  // PVT overlay state
  const showPvt = pvtActive && !!protocol.pvt;

  // ESC key to abort during SSVEP or PVT
  useEffect(() => {
    if (!showFlicker && !showPvt) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (showPvt) setPvtActive(false);
        stopSession();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [showFlicker, showPvt, stopSession]);

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

      {/* PVT session note */}
      {state.phase === "idle" && protocol.pvt && (
        <div className="mb-3">
          <input
            type="text"
            value={pvtNote}
            onChange={(e) => { setPvtNote(e.target.value); pvtNoteRef.current = e.target.value; }}
            placeholder="Session note (e.g. fresh morning, 4h coding, post-lunch)"
            className="w-full px-2.5 py-1.5 text-[11px] font-mono border"
            style={{
              background: "transparent",
              borderColor: "var(--border)",
              color: "var(--text-primary)",
            }}
          />
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
        <div className="mb-3">
          {protocol.pvt && state.secondsLeft > 30 ? (
            /* Long work break for PVT — show large timer and work message */
            <div className="flex flex-col items-center gap-2 py-4">
              <span className="text-[11px] uppercase tracking-wider" style={{ color: "var(--text-dim)" }}>
                Round {state.trialNum}/{protocol.reps} complete — go back to work
              </span>
              <span className="text-3xl font-mono font-bold" style={{ color: "var(--text-primary)" }}>
                {Math.floor(state.secondsLeft / 60)}:{String(Math.floor(state.secondsLeft % 60)).padStart(2, "0")}
              </span>
              <span className="text-[11px] font-mono" style={{ color: "var(--text-dim)" }}>
                until next PVT round (alert sound will play)
              </span>
              <button
                onClick={() => {
                  skipRestRef.current = true;
                }}
                className="mt-2 px-3 py-1.5 text-[11px] font-mono uppercase tracking-wider border transition-colors"
                style={{ background: "transparent", borderColor: "var(--border)", color: "var(--text-secondary)" }}
              >
                SKIP TO NEXT ROUND
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-3">
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

      {/* PVT-B overlay */}
      {protocol.pvt && (
        <PVTOverlay
          durationS={protocol.trialDuration}
          active={showPvt}
          onComplete={handlePvtComplete}
          sharedResultsRef={pvtResultsRef}
        />
      )}
    </div>
  );
}
