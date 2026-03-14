import { useCallback, useEffect, useRef, useState } from "react";
import { CHANNEL_NAMES, type BciEvent } from "../../lib/protocol";

type Phase = "fit" | "blink" | "double_blink" | "nod" | "shake" | "done";
type TrialState = "idle" | "countdown" | "cue" | "hit" | "miss";

const CH_COLORS: Record<string, string> = {
  TP9: "var(--ch-tp9)",
  AF7: "var(--ch-af7)",
  AF8: "var(--ch-af8)",
  TP10: "var(--ch-tp10)",
};

const PHASE_ORDER: Phase[] = ["fit", "blink", "double_blink", "nod", "shake", "done"];

interface BlinkTrial {
  hit: boolean;
  metadata?: Record<string, unknown>;
}

interface PhaseResult {
  trials: BlinkTrial[];
  crossTalk: string[];
}

interface Props {
  headbandState?: { state: string; seconds_in_state: number };
  signalQuality?: Record<string, number>;
  lastEvent: BciEvent | null;
  sendCommand: (cmd: Record<string, unknown>) => void;
  onComplete: () => void;
}


export function CalibrationOverlay({
  headbandState,
  signalQuality,
  lastEvent,
  sendCommand,
  onComplete,
}: Props) {
  const [phase, setPhase] = useState<Phase>("fit");
  const [results, setResults] = useState<Record<string, PhaseResult>>({});

  const isReady = headbandState?.state === "ready";

  const advancePhase = useCallback(
    (phaseResult?: PhaseResult) => {
      setResults((prev) => {
        if (phase !== "fit" && phase !== "done" && phaseResult) {
          return { ...prev, [phase]: phaseResult };
        }
        return prev;
      });
      const currentIdx = PHASE_ORDER.indexOf(phase);
      setPhase(PHASE_ORDER[currentIdx + 1] ?? "done");
    },
    [phase],
  );

  // Done: send calibration command (no auto-dismiss — user closes manually)
  useEffect(() => {
    if (phase !== "done") return;

    setResults((prev) => {
      const blinkResult = prev["blink"];
      if (blinkResult) {
        // Only use captures where baseline was stable — early cold-start captures
        // have wrong baseline context and would skew the calibration.
        const peaks = blinkResult.trials
          .filter((t) => t.hit && t.metadata?.baseline_stable === true && t.metadata?.amplitude_uv != null)
          .map((t) => t.metadata!.amplitude_uv as number);
        if (peaks.length > 0) {
          peaks.sort((a, b) => a - b);
          const median = peaks[Math.floor(peaks.length / 2)];
          sendCommand({ cmd: "calibrate_blink", median_peak_amplitude_uv: median });
        } else {
          // All captures were during cold start — skip calibration, use defaults
          console.warn("Calibration: no stable-baseline captures available, skipping threshold adjustment");
        }
      }
      return prev;
    });
  }, [phase, sendCommand]);

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center"
      style={{ background: "rgba(0, 0, 0, 0.85)" }}
    >
      <div
        className="w-full max-w-md p-6 space-y-6"
        style={{ background: "var(--bg-panel)", border: "1px solid var(--border)" }}
      >
        {/* Header */}
        <div className="flex items-center justify-between">
          <h2
            className="text-sm uppercase tracking-widest font-mono"
            style={{ color: "var(--text-secondary)" }}
          >
            Calibration
          </h2>
          <button
            onClick={onComplete}
            className="text-[11px] font-mono uppercase px-3 py-1 border"
            style={{
              color: "var(--text-dim)",
              borderColor: "var(--border)",
              background: "transparent",
              cursor: "pointer",
            }}
          >
            Skip
          </button>
        </div>

        {phase === "fit" && (
          <FitPhase
            signalQuality={signalQuality}
            isReady={isReady}
            onContinue={() => advancePhase()}
          />
        )}

        {(phase === "blink" || phase === "double_blink") && (
          <CuedBlinkPhase
            key={phase}
            label={phase === "blink" ? "Single Blink" : "Double Blink"}
            instruction={
              phase === "blink"
                ? "Blink naturally when cued"
                : "Blink twice quickly when cued"
            }
            trials={3}
            lastEvent={lastEvent}
            sendCommand={sendCommand}
            onComplete={advancePhase}
          />
        )}

        {(phase === "nod" || phase === "shake") && (
          <PassivePhase
            key={phase}
            eventKind={phase === "nod" ? "nod_yes" : "nod_no"}
            label={phase === "nod" ? "Nod Yes" : "Shake No"}
            instruction={
              phase === "nod"
                ? "Nod slowly 2× — checking for cross-talk"
                : "Shake head slowly 2× — checking for cross-talk"
            }
            crossTalkKinds={["single_blink", "double_blink"]}
            timeoutMs={8000}
            lastEvent={lastEvent}
            onComplete={advancePhase}
          />
        )}

        {phase === "done" && <DonePhase results={results} onClose={onComplete} />}

        {/* Progress dots */}
        <div className="flex justify-center gap-2">
          {PHASE_ORDER.map((p) => (
            <div
              key={p}
              className="w-2 h-2 rounded-full"
              style={{
                background:
                  p === phase
                    ? "var(--status-info)"
                    : PHASE_ORDER.indexOf(p) < PHASE_ORDER.indexOf(phase)
                      ? "var(--status-good)"
                      : "var(--text-dim)",
              }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

// ── FitPhase ──────────────────────────────────────────────────────────────────

function FitPhase({
  signalQuality,
  isReady,
  onContinue,
}: {
  signalQuality?: Record<string, number>;
  isReady: boolean;
  onContinue: () => void;
}) {
  const hasData = signalQuality != null;

  return (
    <div className="space-y-4">
      <p className="text-[13px]" style={{ color: "var(--text-secondary)" }}>
        Position headband for best signal
      </p>
      <div className="grid grid-cols-4 gap-3">
        {CHANNEL_NAMES.map((name) => {
          const q = signalQuality?.[name] ?? -1;
          const good = q > 0.7;
          const noData = q < 0;
          return (
            <div key={name} className="flex flex-col items-center gap-1">
              <div
                className="w-6 h-6 rounded-full"
                style={{
                  background: noData
                    ? "var(--text-dim)"
                    : good
                      ? CH_COLORS[name]
                      : "var(--status-bad)",
                  opacity: good ? 1 : 0.45,
                  boxShadow: good ? `0 0 8px ${CH_COLORS[name]}` : "none",
                  transition: "all 0.4s ease",
                }}
              />
              <span className="text-[10px] font-mono" style={{ color: "var(--text-dim)" }}>
                {name}
              </span>
              <span
                className="text-[10px] font-mono"
                style={{ color: good ? "var(--text-secondary)" : "var(--text-dim)" }}
              >
                {noData ? "—" : `${Math.round(q * 100)}%`}
              </span>
            </div>
          );
        })}
      </div>
      {hasData && !isReady && (
        <p className="text-[11px] font-mono" style={{ color: "var(--status-warn)" }}>
          Poor signal — calibration may be less accurate
        </p>
      )}
      <button
        onClick={onContinue}
        className="w-full py-2 text-[12px] font-mono uppercase tracking-wider border"
        style={{
          color: isReady ? "var(--status-good)" : "var(--text-secondary)",
          borderColor: isReady ? "var(--status-good)" : "var(--border)",
          background: isReady ? "rgba(56, 232, 112, 0.1)" : "transparent",
          cursor: "pointer",
        }}
      >
        {isReady ? "Start Calibration →" : "Proceed anyway →"}
      </button>
    </div>
  );
}

// ── CuedBlinkPhase ────────────────────────────────────────────────────────────
// Sends a capture_blink_sample command to the backend at cue time.
// Backend measures raw frontal deflection for 700ms and returns a blink_sample
// event — independent of the detector threshold. This breaks the chicken-and-egg
// problem where calibration requires the detector to already be calibrated.

function CuedBlinkPhase({
  label,
  instruction,
  trials,
  lastEvent,
  sendCommand,
  onComplete,
}: {
  label: string;
  instruction: string;
  trials: number;
  lastEvent: BciEvent | null;
  sendCommand: (cmd: Record<string, unknown>) => void;
  onComplete: (result: PhaseResult) => void;
}) {
  const [trialState, setTrialState] = useState<TrialState>("idle");
  const [countdown, setCountdown] = useState(3);
  const [completedTrials, setCompletedTrials] = useState<BlinkTrial[]>([]);
  const [resultMeta, setResultMeta] = useState<Record<string, unknown> | null>(null);

  const lastEventRef = useRef<number>(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  useEffect(() => {
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  // Auto-complete when all trials done
  useEffect(() => {
    if (completedTrials.length >= trials) {
      const t = setTimeout(() => {
        onCompleteRef.current({ trials: completedTrials, crossTalk: [] });
      }, 800);
      return () => clearTimeout(t);
    }
  }, [completedTrials, trials]);

  // Receive blink_sample from backend during cue window
  useEffect(() => {
    if (trialState !== "cue") return;
    if (!lastEvent || lastEvent.kind !== "blink_sample") return;
    if (lastEvent.timestamp === lastEventRef.current) return;
    lastEventRef.current = lastEvent.timestamp;

    const meta = lastEvent.metadata as { amplitude_uv: number; half_amplitude_uv: number } | undefined;
    const amp = meta?.amplitude_uv ?? 0;
    const hit = amp < -5; // any meaningful deflection counts
    setResultMeta(meta ?? null);
    setTrialState(hit ? "hit" : "miss");
  }, [lastEvent, trialState]);

  // After showing result, record and go back to idle
  useEffect(() => {
    if (trialState !== "hit" && trialState !== "miss") return;
    const meta = resultMeta ?? undefined;
    const t = setTimeout(() => {
      setCompletedTrials((prev) => [...prev, { hit: trialState === "hit", metadata: meta }]);
      setResultMeta(null);
      setTrialState("idle");
    }, 1200);
    return () => clearTimeout(t);
  }, [trialState, resultMeta]);

  function startCue() {
    let n = 3;
    setCountdown(n);
    setTrialState("countdown");

    intervalRef.current = setInterval(() => {
      n -= 1;
      setCountdown(n);
      if (n <= 0) {
        clearInterval(intervalRef.current!);
        setTrialState("cue");
        // Tell backend to open a 700ms raw capture window
        sendCommand({ cmd: "capture_blink_sample" });
      }
    }, 1000);
  }

  const currentTrial = completedTrials.length + 1;
  const allDone = completedTrials.length >= trials;

  // Dot color: green = detected, yellow = weak, red = nothing
  function dotColor(amp: number | undefined, hit: boolean) {
    if (!hit) return "var(--status-bad)";
    if (amp != null && amp > -15) return "var(--status-warn)"; // weak
    return "var(--status-good)";
  }

  return (
    <div className="space-y-4">
      <p className="text-[13px]" style={{ color: "var(--text-secondary)" }}>
        {instruction}
      </p>

      <div className="text-[11px] font-mono text-center" style={{ color: "var(--text-dim)" }}>
        {allDone ? "Done" : `Trial ${currentTrial} / ${trials}`}
      </div>

      {/* Cue box */}
      <div
        className="h-20 flex flex-col items-center justify-center rounded gap-1"
        style={{
          background:
            trialState === "cue"
              ? "rgba(56, 232, 112, 0.15)"
              : trialState === "hit"
                ? "rgba(56, 232, 112, 0.2)"
                : trialState === "miss"
                  ? "rgba(232, 72, 104, 0.08)"
                  : "var(--bg-input)",
          border: `1px solid ${
            trialState === "cue" || trialState === "hit"
              ? "var(--status-good)"
              : trialState === "miss"
                ? "var(--status-bad)"
                : "var(--border)"
          }`,
          transition: "all 0.15s ease",
        }}
      >
        {trialState === "idle" && (
          <span className="text-[12px] font-mono" style={{ color: "var(--text-dim)" }}>
            {allDone ? "Complete" : "Press Start when ready"}
          </span>
        )}
        {trialState === "countdown" && (
          <span
            className="text-[52px] font-mono font-bold"
            style={{ color: "var(--text-secondary)", lineHeight: 1 }}
          >
            {countdown}
          </span>
        )}
        {trialState === "cue" && (
          <span
            className="text-[22px] font-mono font-bold uppercase tracking-widest"
            style={{ color: "var(--status-good)" }}
          >
            {label}!
          </span>
        )}
        {trialState === "hit" && (
          <>
            <span className="text-[18px] font-mono" style={{ color: "var(--status-good)" }}>
              ✓ Detected
            </span>
            {resultMeta?.amplitude_uv != null && (
              <span className="text-[11px] font-mono" style={{ color: "var(--text-dim)" }}>
                {(resultMeta.amplitude_uv as number).toFixed(1)} µV
                {resultMeta.baseline_stable === false && " (unstable baseline)"}
              </span>
            )}
          </>
        )}
        {trialState === "miss" && (
          <>
            <span className="text-[14px] font-mono" style={{ color: "var(--status-bad)" }}>
              Weak signal
            </span>
            {resultMeta?.amplitude_uv != null && (
              <span className="text-[11px] font-mono" style={{ color: "var(--text-dim)" }}>
                {(resultMeta.amplitude_uv as number).toFixed(1)} µV — still recorded
              </span>
            )}
          </>
        )}
      </div>

      {/* Trial result dots */}
      <div className="flex justify-center gap-2">
        {Array.from({ length: trials }).map((_, i) => {
          const t = completedTrials[i];
          const active = !t && i === completedTrials.length && trialState !== "idle";
          return (
            <div
              key={i}
              className="w-3 h-3 rounded-full"
              style={{
                background: t
                  ? dotColor(t.metadata?.amplitude_uv as number | undefined, t.hit)
                  : active
                    ? "var(--status-info)"
                    : "var(--border)",
                transition: "background 0.2s ease",
              }}
            />
          );
        })}
      </div>

      {/* Start button — only in idle state */}
      {trialState === "idle" && !allDone && (
        <button
          onClick={startCue}
          className="w-full py-2 text-[12px] font-mono uppercase tracking-wider border"
          style={{
            color: "var(--text-secondary)",
            borderColor: "var(--border)",
            background: "transparent",
            cursor: "pointer",
          }}
        >
          {completedTrials.length === 0 ? "Start" : "Next Trial →"}
        </button>
      )}
    </div>
  );
}

// ── PassivePhase (nod / shake) ────────────────────────────────────────────────

function PassivePhase({
  eventKind,
  label,
  instruction,
  crossTalkKinds,
  timeoutMs,
  lastEvent,
  onComplete,
}: {
  eventKind: string;
  label: string;
  instruction: string;
  crossTalkKinds: string[];
  timeoutMs: number;
  lastEvent: BciEvent | null;
  onComplete: (result: PhaseResult) => void;
}) {
  const [detected, setDetected] = useState(0);
  const [crossTalk, setCrossTalk] = useState<string[]>([]);
  const lastEventRef = useRef<number>(0);
  // Refs mirror state so the timeout closure always sees current values
  const detectedRef = useRef(0);
  const crossTalkRef = useRef<string[]>([]);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  const finish = useCallback((detectedCount: number, ct: string[]) => {
    onCompleteRef.current({
      trials: Array.from({ length: detectedCount }, () => ({ hit: true })),
      crossTalk: ct,
    });
  }, []);

  useEffect(() => {
    // Use refs in the timeout to avoid stale closure over state
    const t = setTimeout(
      () => finish(detectedRef.current, crossTalkRef.current),
      timeoutMs,
    );
    return () => clearTimeout(t);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!lastEvent) return;
    if (lastEvent.timestamp === lastEventRef.current) return;
    lastEventRef.current = lastEvent.timestamp;

    if (lastEvent.kind === eventKind) {
      detectedRef.current += 1;
      setDetected(detectedRef.current);
    } else if (crossTalkKinds.includes(lastEvent.kind)) {
      crossTalkRef.current = [...crossTalkRef.current, lastEvent.kind];
      setCrossTalk(crossTalkRef.current);
    }
  }, [lastEvent, eventKind, crossTalkKinds]);

  return (
    <div className="space-y-4">
      <p className="text-[13px]" style={{ color: "var(--text-secondary)" }}>
        {instruction}
      </p>
      <div
        className="h-14 flex items-center justify-center"
        style={{ border: "1px solid var(--border)", background: "var(--bg-input)" }}
      >
        <span className="text-[13px] font-mono" style={{ color: "var(--text-secondary)" }}>
          {label} — {detected} detected
        </span>
      </div>
      {crossTalk.length > 0 && (
        <div className="text-[11px] font-mono" style={{ color: "var(--status-warn)" }}>
          Cross-talk: {crossTalk.map((k) => k.replace(/_/g, " ")).join(", ")}
        </div>
      )}
      <button
        onClick={() => finish(detectedRef.current, crossTalkRef.current)}
        className="w-full py-1.5 text-[11px] font-mono uppercase border"
        style={{
          color: "var(--text-dim)",
          borderColor: "var(--border)",
          background: "transparent",
          cursor: "pointer",
        }}
      >
        Skip →
      </button>
    </div>
  );
}

// ── DonePhase ─────────────────────────────────────────────────────────────────

function DonePhase({
  results,
  onClose,
}: {
  results: Record<string, PhaseResult>;
  onClose: () => void;
}) {
  const phases = ["blink", "double_blink", "nod", "shake"] as const;
  const labels: Record<string, string> = {
    blink: "Single Blink",
    double_blink: "Double Blink",
    nod: "Nod Yes",
    shake: "Shake No",
  };

  return (
    <div className="space-y-3">
      <p className="text-[14px] text-center" style={{ color: "var(--status-good)" }}>
        Calibration Complete
      </p>
      <div className="space-y-1">
        {phases.map((p) => {
          const r = results[p];
          const hits = r?.trials.filter((t) => t.hit).length ?? 0;
          const total = r?.trials.length ?? 0;
          const ok = hits > 0 && hits === total;
          return (
            <div key={p} className="flex items-center justify-between text-[11px] font-mono">
              <span style={{ color: "var(--text-secondary)" }}>{labels[p]}</span>
              <span
                style={{
                  color: ok
                    ? "var(--status-good)"
                    : hits > 0
                      ? "var(--status-warn)"
                      : "var(--status-bad)",
                }}
              >
                {r ? `${hits}/${total}` : "skipped"}
                {r && r.crossTalk.length > 0 && " ⚠"}
              </span>
            </div>
          );
        })}
      </div>
      <button
        onClick={onClose}
        className="w-full py-2 text-[12px] font-mono uppercase tracking-wider border"
        style={{
          color: "var(--status-good)",
          borderColor: "var(--status-good)",
          background: "rgba(56, 232, 112, 0.1)",
          cursor: "pointer",
        }}
      >
        Close
      </button>
    </div>
  );
}
