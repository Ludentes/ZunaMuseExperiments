# Fitting & Calibration Protocol — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a per-session calibration flow that measures the user's blink profile and tunes detector thresholds, plus quality-gated confidence that scales event reliability by signal quality.

**Architecture:** Backend BlinkDetector gets blink profile metadata, a calibration method, and quality-gated confidence. Server broadcasts metadata and handles a `calibrate_blink` command. Frontend CalibrationOverlay guides users through fit check + command verification (blink, double blink, nod, shake). Existing demo components gate actions on confidence threshold.

**Tech Stack:** Python (backend detectors + server), React 19 + TypeScript (frontend), WebSocket JSON protocol.

**Design doc:** `docs/plans/2026-03-13-fitting-calibration-protocol-design.md`

---

### Task 1: BlinkDetector — blink profile metadata + quality-gated confidence

**Files:**
- Modify: `backend/pipeline/stages/detectors.py:79-524`
- Test: `tests/test_pipeline_stages_detectors.py`

**Step 1: Write failing tests**

Add to `tests/test_pipeline_stages_detectors.py`:

```python
def test_blink_detector_emits_metadata():
    """Blink events must include amplitude_uv, half_amplitude_uv, onset_slope, duration_ms."""
    rng = np.random.default_rng(42)
    detector = BlinkDetector()
    t = _establish_baseline(detector, rng)
    events, t = _inject_blink(detector, rng, t, blink_amp=-200.0)
    flush_events = _flush_classify(detector, rng, t)
    all_events = events + flush_events
    blink_events = [e for e in all_events if "blink" in e.kind]
    assert len(blink_events) >= 1
    meta = blink_events[0].metadata
    assert "amplitude_uv" in meta
    assert "half_amplitude_uv" in meta
    assert "onset_slope" in meta
    assert "duration_ms" in meta
    assert meta["amplitude_uv"] < -50  # strong blink
    assert meta["duration_ms"] > 0


def test_blink_detector_set_signal_quality_scales_confidence():
    """Quality-gated confidence: low quality → low confidence."""
    rng = np.random.default_rng(42)
    detector = BlinkDetector()
    t = _establish_baseline(detector, rng)

    # Full quality → base confidence
    detector.set_signal_quality(1.0)
    events, t = _inject_blink(detector, rng, t, blink_amp=-200.0)
    flush_events = _flush_classify(detector, rng, t)
    all_events = events + flush_events
    blink_events = [e for e in all_events if "blink" in e.kind]
    assert len(blink_events) >= 1
    high_conf = blink_events[0].confidence
    assert high_conf >= 0.85  # base single_blink confidence = 0.9

    # Low quality → scaled down
    detector2 = BlinkDetector()
    t2 = _establish_baseline(detector2, rng)
    detector2.set_signal_quality(0.3)
    events2, t2 = _inject_blink(detector2, rng, t2, blink_amp=-200.0)
    flush2 = _flush_classify(detector2, rng, t2)
    blink2 = [e for e in events2 + flush2 if "blink" in e.kind]
    assert len(blink2) >= 1
    low_conf = blink2[0].confidence
    assert low_conf < 0.5  # 0.9 * 0.3 = 0.27


def test_blink_detector_set_calibrated_threshold():
    """Calibration adjusts threshold_sd based on measured blink amplitude."""
    rng = np.random.default_rng(42)
    detector = BlinkDetector()
    t = _establish_baseline(detector, rng)
    original_sd = detector.threshold_sd

    # Simulate a calibration: median half-amplitude is -25µV
    # With baseline ~0 and MAD-based robust_sd ~7-15, this should adjust threshold_sd
    detector.set_calibrated_threshold(-25.0)
    assert detector.threshold_sd >= 1.5  # floor
    # Threshold may change or stay depending on baseline stats,
    # but method must not crash and must log
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pipeline_stages_detectors.py::test_blink_detector_emits_metadata tests/test_pipeline_stages_detectors.py::test_blink_detector_set_signal_quality_scales_confidence tests/test_pipeline_stages_detectors.py::test_blink_detector_set_calibrated_threshold -v`
Expected: FAIL — `set_signal_quality` and `set_calibrated_threshold` don't exist, metadata keys missing.

**Step 3: Implement**

In `backend/pipeline/stages/detectors.py`, make these changes:

**3a.** In `__init__` (after line 163), add:

```python
        self._frontal_quality: float = 1.0  # signal quality scalar for confidence gating
```

**3b.** Change `_pending_blinks` type (line 148):

```python
        self._pending_blinks: deque[tuple[float, float]] = deque(maxlen=10)  # (timestamp, amplitude_uv)
```

**3c.** Add new methods after `_update_baseline` (after line 180):

```python
    def set_signal_quality(self, frontal_quality: float) -> None:
        """Update frontal signal quality (0-1). Scales event confidence."""
        self._frontal_quality = max(0.0, min(1.0, frontal_quality))

    def set_calibrated_threshold(self, median_half_amplitude_uv: float) -> None:
        """Set threshold_sd based on calibration blink measurements.

        Uses the half-amplitude (not peak) because that's where we can first
        be confident a blink is happening — responding at half-amplitude is
        ~50ms faster than waiting for the peak.
        """
        robust_sd = 1.4826 * self._baseline_mad
        if robust_sd > 0:
            blink_sds = abs(median_half_amplitude_uv - self._baseline_median) / robust_sd
            self.threshold_sd = max(1.5, blink_sds * 0.5)
        self._log.info(
            "Calibrated: threshold_sd=%.2f (half_amp=%.1f µV, baseline=%.1f, robust_sd=%.1f)",
            self.threshold_sd, median_half_amplitude_uv, self._baseline_median, robust_sd,
        )
```

**3d.** Change `_check_shape` to return metadata dict instead of bool. Rename to `_check_shape_and_profile`:

Replace the `_check_shape` method (lines 232-336) with:

```python
    def _check_shape(self) -> tuple[bool, dict]:
        """Validate blink shape and extract profile metadata.

        Returns (passed, metadata) where metadata contains amplitude, half-amplitude,
        onset slope, and duration for calibration data collection.
        """
        empty_meta: dict = {}
        if not self._buf_filled and self._buf_pos < self._HALF_WIN * 2:
            return True, empty_meta  # not enough data, accept

        # Reconstruct ordered buffer
        if self._buf_filled:
            buf = np.concatenate([
                self._frontal_buf[self._buf_pos:],
                self._frontal_buf[:self._buf_pos],
            ])
        else:
            buf = self._frontal_buf[:self._buf_pos]

        # Find the deepest point (blink peak is most negative)
        min_idx = int(np.argmin(buf))
        peak_val = float(buf[min_idx])
        half_amp = peak_val / 2.0

        # Find left boundary at half-amplitude
        left_idx = min_idx
        for i in range(min_idx - 1, -1, -1):
            if buf[i] >= half_amp:
                left_idx = i
                break
        else:
            left_idx = 0

        # Find right boundary at half-amplitude
        right_idx = min_idx
        for i in range(min_idx + 1, len(buf)):
            if buf[i] >= half_amp:
                right_idx = i
                break
        else:
            right_idx = len(buf) - 1

        # Duration check
        contiguous = right_idx - left_idx + 1
        dur_ms = contiguous / 256.0 * 1000.0

        if dur_ms < self.min_deflection_ms:
            self._log.debug("SHAPE: too brief %.0fms < %.0fms", dur_ms, self.min_deflection_ms)
            return False, empty_meta
        if dur_ms > self.max_deflection_ms:
            self._log.debug("SHAPE: too broad %.0fms > %.0fms", dur_ms, self.max_deflection_ms)
            return False, empty_meta

        # R² tent fitting: need at least 4 samples per half for meaningful regression
        downstroke = buf[left_idx:min_idx + 1]
        upstroke = buf[min_idx:right_idx + 1]

        if len(downstroke) < 4 or len(upstroke) < 4:
            # Too short for R², build metadata from what we have
            meta = {
                "amplitude_uv": round(peak_val, 1),
                "half_amplitude_uv": round(half_amp, 1),
                "onset_slope": 0.0,
                "duration_ms": round(dur_ms, 1),
            }
            return True, meta  # accept based on duration alone

        # Fit inner 80% of each half. Returns (R², slope).
        def r_squared_and_slope(segment: np.ndarray) -> tuple[float, float]:
            n = len(segment)
            start = int(n * 0.1)
            end = int(n * 0.9)
            if end - start < 3:
                return 1.0, 0.0  # too few points, accept
            inner = segment[start:end]
            x = np.arange(len(inner), dtype=np.float64)
            coeffs = np.polyfit(x, inner, 1)
            slope = float(coeffs[0])
            predicted = np.polyval(coeffs, x)
            ss_res = np.sum((inner - predicted) ** 2)
            ss_tot = np.sum((inner - np.mean(inner)) ** 2)
            if ss_tot < 1e-10:
                return 1.0, slope
            return float(1.0 - ss_res / ss_tot), slope

        r2_down, slope_down = r_squared_and_slope(downstroke)
        r2_up, slope_up = r_squared_and_slope(upstroke)

        # Build metadata
        meta = {
            "amplitude_uv": round(peak_val, 1),
            "half_amplitude_uv": round(half_amp, 1),
            "onset_slope": round(slope_down, 2),
            "duration_ms": round(dur_ms, 1),
        }

        # Slope direction check: downstroke must go down, upstroke must go up.
        blink_amplitude = abs(peak_val - float(np.mean([buf[left_idx], buf[right_idx]])))
        if blink_amplitude > 1.0:
            min_slope = blink_amplitude * 0.15 / max(len(downstroke), len(upstroke))
            if slope_down > -min_slope or slope_up < min_slope:
                self._log.debug(
                    "SHAPE slope: down=%.2f up=%.2f (min_mag=%.2f) → REJECT (plateau)",
                    slope_down, slope_up, min_slope)
                return False, empty_meta

        self._log.debug("SHAPE R²: down=%.2f up=%.2f slopes=%.2f/%.2f → ACCEPT",
                       r2_down, r2_up, slope_down, slope_up)
        return True, meta
```

**3e.** Update `_try_emit_blink` to capture metadata from shape check (line 428-430):

Change:
```python
        # Guard 3: shape validation — reject non-tent-shaped deflections
        if not self._check_shape():
            self._log.debug("REJECTED by shape guard")
            return
```

To:
```python
        # Guard 3: shape validation — reject non-tent-shaped deflections
        shape_ok, blink_meta = self._check_shape()
        if not shape_ok:
            self._log.debug("REJECTED by shape guard")
            return
```

**3f.** Update the blink candidate registration (line 440) to store amplitude:

Change:
```python
            self._pending_blinks.append(now)
```

To:
```python
            amplitude = blink_meta.get("amplitude_uv", 0.0) if blink_meta else 0.0
            self._pending_blinks.append((now, amplitude))
```

**3g.** Update the event emission block (lines 510-524) to include metadata and quality-scaled confidence:

Change:
```python
        if self._pending_blinks and now >= self._classify_deadline:
            count = len(self._pending_blinks)
            self._pending_blinks.clear()
            self._log.debug("EMITTING: %d blink(s) in window", count)

            if count >= 2:
                frame.events.append(Event(
                    kind="double_blink", timestamp=now, confidence=0.85,
                    channel="AF7+AF8",
                ))
            else:
                frame.events.append(Event(
                    kind="single_blink", timestamp=now, confidence=0.9,
                    channel="AF7+AF8",
                ))
```

To:
```python
        if self._pending_blinks and now >= self._classify_deadline:
            count = len(self._pending_blinks)
            # Use the deepest amplitude from pending blinks for metadata
            deepest_amp = min(amp for _, amp in self._pending_blinks)
            self._pending_blinks.clear()
            self._log.debug("EMITTING: %d blink(s) in window", count)

            # Re-run shape analysis to get full metadata for the emitted event
            _, emit_meta = self._check_shape()

            if count >= 2:
                base_conf = 0.85
                frame.events.append(Event(
                    kind="double_blink", timestamp=now,
                    confidence=round(base_conf * self._frontal_quality, 2),
                    channel="AF7+AF8",
                    metadata=emit_meta,
                ))
            else:
                base_conf = 0.9
                frame.events.append(Event(
                    kind="single_blink", timestamp=now,
                    confidence=round(base_conf * self._frontal_quality, 2),
                    channel="AF7+AF8",
                    metadata=emit_meta,
                ))
```

**3h.** Store `blink_meta` on the instance so it persists between `_try_emit_blink` and event emission. Add to `__init__` (after line 163):

```python
        self._last_blink_meta: dict = {}
```

And at end of `_try_emit_blink`, before the refractory check succeeds (after the shape_ok/blink_meta line in step 3e), store it:

```python
        self._last_blink_meta = blink_meta
```

Then in step 3g, use `self._last_blink_meta` instead of re-running `_check_shape()`:

```python
            emit_meta = self._last_blink_meta or {}
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pipeline_stages_detectors.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add backend/pipeline/stages/detectors.py tests/test_pipeline_stages_detectors.py
git commit -m "feat: BlinkDetector blink profile metadata + quality-gated confidence + calibration"
```

---

### Task 2: Server — broadcast metadata + calibrate_blink command + quality bridge

**Files:**
- Modify: `backend/main.py:338-345` (broadcast), `backend/main.py:105-179` (command handler), `backend/main.py:366-425` (metrics loop)

**Step 1: Write a simple integration test**

Create `tests/test_calibrate_command.py`:

```python
"""Test that BlinkDetector can be found and calibrated via pipeline stages."""
from backend.pipeline.factory import create_default_pipeline
from backend.pipeline.stages.detectors import BlinkDetector


def test_find_blink_detector_in_pipeline():
    """Pipeline contains a BlinkDetector accessible by name."""
    pipeline = create_default_pipeline()
    detector = None
    for stage in pipeline.stages:
        if getattr(stage, 'name', None) == 'blink_detector':
            detector = stage
            break
    assert detector is not None
    assert isinstance(detector, BlinkDetector)


def test_blink_detector_has_calibration_methods():
    """BlinkDetector exposes calibration and quality methods."""
    detector = BlinkDetector()
    assert hasattr(detector, 'set_calibrated_threshold')
    assert hasattr(detector, 'set_signal_quality')
    detector.set_signal_quality(0.5)
    assert detector._frontal_quality == 0.5
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_calibrate_command.py -v`
Expected: FAIL (methods don't exist yet if Task 1 not done) or PASS (if Task 1 done).

**Step 3: Implement server changes**

**3a.** Add metadata to bci_event broadcast. In `backend/main.py`, change lines 339-345:

From:
```python
                    for event in fast_frame.events:
                        await self._broadcast_text(json.dumps({
                            "type": "bci_event",
                            "kind": event.kind,
                            "confidence": event.confidence,
                            "channel": event.channel,
                            "timestamp": event.timestamp,
                        }))
```

To:
```python
                    for event in fast_frame.events:
                        await self._broadcast_text(json.dumps({
                            "type": "bci_event",
                            "kind": event.kind,
                            "confidence": event.confidence,
                            "channel": event.channel,
                            "timestamp": event.timestamp,
                            "metadata": event.metadata,
                        }))
```

**3b.** Add `_get_blink_detector` helper. After `_get_zuna_stage` (line 274):

```python
    def _get_blink_detector(self):
        """Find BlinkDetector in pipeline."""
        for stage in self._pipeline.stages:
            if getattr(stage, 'name', None) == 'blink_detector':
                return stage
        return None
```

**3c.** Add `calibrate_blink` command handler. In `_handle_command`, after the `discard_last_recording` elif block (after line 179):

```python
        elif action == "calibrate_blink":
            detector = self._get_blink_detector()
            if detector:
                median_half_amp = cmd.get("median_half_amplitude_uv", -25.0)
                detector.set_calibrated_threshold(median_half_amp)
                log.info("Calibrate blink: median_half_amp=%.1f µV", median_half_amp)
```

**3d.** Add quality → detector bridge in metrics loop. In `_metrics_loop`, after `metrics = frame_to_metrics(frame)` (line 415), add:

```python
            # Bridge signal quality to blink detector for confidence gating
            from backend.pipeline.stages.features import SignalQualityResult
            sq = frame.get(SignalQualityResult)
            if sq:
                detector = self._get_blink_detector()
                if detector:
                    frontal_avg = (sq.quality.get("AF7", 0) + sq.quality.get("AF8", 0)) / 2
                    detector.set_signal_quality(frontal_avg)
```

**Step 4: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add backend/main.py tests/test_calibrate_command.py
git commit -m "feat: broadcast event metadata + calibrate_blink command + quality bridge"
```

---

### Task 3: Frontend — update types and hook

**Files:**
- Modify: `frontend/src/lib/protocol.ts:81-87`
- Modify: `frontend/src/hooks/useSensorStream.ts:63-64`

**Step 1: Add `metadata` to BciEvent interface**

In `frontend/src/lib/protocol.ts`, change lines 81-87:

From:
```typescript
export interface BciEvent {
  type: "bci_event";
  kind: string;       // "single_blink" | "double_blink" | "triple_blink" | "clench"
  confidence: number;
  timestamp: number;
  channel?: string;
}
```

To:
```typescript
export interface BciEvent {
  type: "bci_event";
  kind: string;       // "single_blink" | "double_blink" | "triple_blink" | "clench"
  confidence: number;
  timestamp: number;
  channel?: string;
  metadata?: Record<string, unknown>;
}
```

**Step 2: Pass metadata through in useSensorStream**

In `frontend/src/hooks/useSensorStream.ts`, the line that stores bci events (line 64):

```typescript
            eventsRef.current = [...eventsRef.current.slice(-49), msg as BciEvent];
```

This already works because `msg as BciEvent` will include `metadata` if present in the JSON. The type definition change is sufficient.

**Step 3: Verify frontend builds**

Run: `cd frontend && pnpm build`
Expected: No type errors.

**Step 4: Commit**

```bash
git add frontend/src/lib/protocol.ts
git commit -m "feat: add metadata field to BciEvent type"
```

---

### Task 4: Frontend — confidence gating in demo components

**Files:**
- Modify: `frontend/src/components/demo/BlinkFlash.tsx:14-16`
- Modify: `frontend/src/components/demo/CommandArrow.tsx:30-33`
- Modify: `frontend/src/components/demo/KioskPlayer.tsx:23-28`
- Modify: `frontend/src/components/demo/EventLog.tsx:59-73`

**Step 1: Add confidence gate to BlinkFlash**

In `BlinkFlash.tsx`, after line 16 (`if (!lastEvent.kind.includes("blink")) return;`), add:

```typescript
    if ((lastEvent.confidence ?? 1) < 0.6) return;
```

**Step 2: Add confidence gate to CommandArrow**

In `CommandArrow.tsx`, after line 32 (`const target = TARGETS[lastEvent.kind];`), before `if (!target) return;`, add:

```typescript
    if ((lastEvent.confidence ?? 1) < 0.6) return;
```

**Step 3: Add confidence gate to KioskPlayer**

In `KioskPlayer.tsx`, after line 25 (`if (lastEvent.kind !== "double_blink") return;`), add:

```typescript
    if ((lastEvent.confidence ?? 1) < 0.6) return;
```

**Step 4: Dim low-confidence events in EventLog**

In `EventLog.tsx`, change the event row rendering (lines 60-73):

From:
```tsx
        {reversed.map((ev, i) => (
          <div key={`${ev.timestamp}-${i}`} className="flex items-center gap-2">
            <span style={{ color: "var(--text-dim)" }}>{formatTime(ev.timestamp)}</span>
            <span style={{ color: KIND_COLORS[ev.kind] ?? "var(--text-secondary)" }}>
              {ev.kind.replace(/_/g, " ")}
            </span>
            <span style={{ color: "var(--text-dim)" }}>
              ({(ev.confidence * 100).toFixed(0)}%)
            </span>
            <span style={{ color: "var(--text-dim)" }}>→</span>
            <span style={{ color: "var(--status-info)" }}>
              {KIND_ACTIONS[ev.kind] ?? ev.kind}
            </span>
          </div>
        ))}
```

To:
```tsx
        {reversed.map((ev, i) => {
          const dimmed = (ev.confidence ?? 1) < 0.6;
          return (
            <div
              key={`${ev.timestamp}-${i}`}
              className="flex items-center gap-2"
              style={{ opacity: dimmed ? 0.4 : 1 }}
            >
              <span style={{ color: "var(--text-dim)" }}>{formatTime(ev.timestamp)}</span>
              <span style={{ color: KIND_COLORS[ev.kind] ?? "var(--text-secondary)" }}>
                {ev.kind.replace(/_/g, " ")}
              </span>
              <span style={{ color: "var(--text-dim)" }}>
                ({(ev.confidence * 100).toFixed(0)}%)
              </span>
              <span style={{ color: "var(--text-dim)" }}>→</span>
              <span style={{ color: dimmed ? "var(--text-dim)" : "var(--status-info)" }}>
                {KIND_ACTIONS[ev.kind] ?? ev.kind}
              </span>
            </div>
          );
        })}
```

**Step 5: Verify frontend builds**

Run: `cd frontend && pnpm build`
Expected: No type errors.

**Step 6: Commit**

```bash
git add frontend/src/components/demo/BlinkFlash.tsx frontend/src/components/demo/CommandArrow.tsx frontend/src/components/demo/KioskPlayer.tsx frontend/src/components/demo/EventLog.tsx
git commit -m "feat: confidence gating in demo components (>0.6 threshold)"
```

---

### Task 5: CalibrationOverlay component

**Files:**
- Create: `frontend/src/components/demo/CalibrationOverlay.tsx`

**Step 1: Create the component**

Create `frontend/src/components/demo/CalibrationOverlay.tsx`:

```tsx
import { useCallback, useEffect, useRef, useState } from "react";
import { CHANNEL_NAMES, type BciEvent } from "../../lib/protocol";

type Phase = "fit" | "blink" | "double_blink" | "nod" | "shake" | "done";

interface PhaseConfig {
  label: string;
  instruction: string;
  eventKind: string;
  required: number;
  timeoutMs: number;
  crossTalkKinds?: string[];
}

const PHASES: Record<Exclude<Phase, "fit" | "done">, PhaseConfig> = {
  blink: {
    label: "Single Blink",
    instruction: "Blink naturally",
    eventKind: "single_blink",
    required: 3,
    timeoutMs: 15000,
  },
  double_blink: {
    label: "Double Blink",
    instruction: "Blink twice quickly",
    eventKind: "double_blink",
    required: 2,
    timeoutMs: 15000,
  },
  nod: {
    label: "Nod Yes",
    instruction: "Nod your head yes",
    eventKind: "nod_yes",
    required: 2,
    timeoutMs: 10000,
    crossTalkKinds: ["single_blink", "double_blink"],
  },
  shake: {
    label: "Shake No",
    instruction: "Shake your head no",
    eventKind: "nod_no",
    required: 2,
    timeoutMs: 10000,
    crossTalkKinds: ["single_blink", "double_blink"],
  },
};

const PHASE_ORDER: Phase[] = ["fit", "blink", "double_blink", "nod", "shake", "done"];

const CH_COLORS: Record<string, string> = {
  TP9: "var(--ch-tp9)",
  AF7: "var(--ch-af7)",
  AF8: "var(--ch-af8)",
  TP10: "var(--ch-tp10)",
};

interface Props {
  headbandState?: { state: string; seconds_in_state: number };
  signalQuality?: Record<string, number>;
  lastEvent: BciEvent | null;
  sendCommand: (cmd: Record<string, unknown>) => void;
  onComplete: () => void;
}

interface PhaseResult {
  detected: number;
  required: number;
  crossTalk: string[];
  blinkMeta: Array<Record<string, unknown>>;
}

export function CalibrationOverlay({
  headbandState,
  signalQuality,
  lastEvent,
  sendCommand,
  onComplete,
}: Props) {
  const [phase, setPhase] = useState<Phase>("fit");
  const [detected, setDetected] = useState(0);
  const [crossTalk, setCrossTalk] = useState<string[]>([]);
  const [blinkMeta, setBlinkMeta] = useState<Array<Record<string, unknown>>>([]);
  const [results, setResults] = useState<Record<string, PhaseResult>>({});
  const [qualityDrop, setQualityDrop] = useState(false);
  const [returnPhase, setReturnPhase] = useState<Phase | null>(null);
  const lastEventRef = useRef<number>(0);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Get frontal quality average
  const frontalQuality =
    signalQuality
      ? ((signalQuality["AF7"] ?? 0) + (signalQuality["AF8"] ?? 0)) / 2
      : 0;

  // Quality drop detection during test phases
  useEffect(() => {
    if (phase === "fit" || phase === "done") return;
    if (frontalQuality < 0.5 && !qualityDrop) {
      setQualityDrop(true);
      setReturnPhase(phase);
      // Clear current phase data
      setDetected(0);
      setCrossTalk([]);
      setBlinkMeta([]);
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      setPhase("fit");
    }
  }, [frontalQuality, phase, qualityDrop]);

  // Reset quality drop flag when returning to fit
  useEffect(() => {
    if (phase === "fit") {
      setQualityDrop(false);
    }
  }, [phase]);

  // Track events during test phases
  useEffect(() => {
    if (phase === "fit" || phase === "done") return;
    if (!lastEvent) return;
    if (lastEvent.timestamp === lastEventRef.current) return;
    lastEventRef.current = lastEvent.timestamp;

    const config = PHASES[phase as keyof typeof PHASES];
    if (!config) return;

    if (lastEvent.kind === config.eventKind) {
      setDetected((d) => {
        const newCount = d + 1;
        // Collect blink metadata during blink phase
        if (phase === "blink" && lastEvent.metadata) {
          setBlinkMeta((prev) => [...prev, lastEvent.metadata!]);
        }
        return newCount;
      });
    } else if (config.crossTalkKinds?.includes(lastEvent.kind)) {
      setCrossTalk((prev) => [...prev, lastEvent.kind]);
    }
  }, [lastEvent, phase]);

  // Auto-advance when required count reached
  useEffect(() => {
    if (phase === "fit" || phase === "done") return;
    const config = PHASES[phase as keyof typeof PHASES];
    if (!config) return;
    if (detected >= config.required) {
      advancePhase();
    }
  }, [detected, phase]);

  // Timeout for test phases
  useEffect(() => {
    if (phase === "fit" || phase === "done") return;
    const config = PHASES[phase as keyof typeof PHASES];
    if (!config) return;

    timeoutRef.current = setTimeout(() => {
      advancePhase();
    }, config.timeoutMs);

    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, [phase]);

  const advancePhase = useCallback(() => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);

    // Save results for current phase
    if (phase !== "fit" && phase !== "done") {
      const config = PHASES[phase as keyof typeof PHASES];
      setResults((prev) => ({
        ...prev,
        [phase]: {
          detected,
          required: config.required,
          crossTalk: [...crossTalk],
          blinkMeta: [...blinkMeta],
        },
      }));
    }

    // Move to next phase
    const currentIdx = PHASE_ORDER.indexOf(phase);
    const nextPhase = PHASE_ORDER[currentIdx + 1] ?? "done";

    // Reset counters for next phase
    setDetected(0);
    setCrossTalk([]);
    if (nextPhase !== "blink") setBlinkMeta([]); // preserve blink meta
    setPhase(nextPhase);
  }, [phase, detected, crossTalk, blinkMeta]);

  // Done phase: send calibration and auto-dismiss
  useEffect(() => {
    if (phase !== "done") return;

    // Compute calibration data from blink phase results
    const blinkResult = results["blink"];
    if (blinkResult && blinkResult.blinkMeta.length > 0) {
      const halfAmps = blinkResult.blinkMeta
        .map((m) => m.half_amplitude_uv as number)
        .filter((v) => typeof v === "number" && !isNaN(v));

      if (halfAmps.length > 0) {
        halfAmps.sort((a, b) => a - b);
        const median = halfAmps[Math.floor(halfAmps.length / 2)];
        sendCommand({
          cmd: "calibrate_blink",
          median_half_amplitude_uv: median,
        });
      }
    }

    const timer = setTimeout(onComplete, 2000);
    return () => clearTimeout(timer);
  }, [phase, results, sendCommand, onComplete]);

  const isReady = headbandState?.state === "ready";

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center"
      style={{ background: "rgba(0, 0, 0, 0.85)" }}
    >
      <div
        className="w-full max-w-md p-6 space-y-6"
        style={{
          background: "var(--bg-panel)",
          border: "1px solid var(--border)",
        }}
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

        {/* Phase content */}
        {phase === "fit" && (
          <FitPhase
            signalQuality={signalQuality}
            isReady={isReady}
            qualityDrop={qualityDrop}
            returnPhase={returnPhase}
            onContinue={() => {
              const next = returnPhase ?? "blink";
              setReturnPhase(null);
              setPhase(next);
            }}
          />
        )}

        {phase !== "fit" && phase !== "done" && (
          <TestPhase
            phase={phase}
            config={PHASES[phase as keyof typeof PHASES]}
            detected={detected}
            crossTalk={crossTalk}
          />
        )}

        {phase === "done" && <DonePhase results={results} />}

        {/* Phase progress dots */}
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

function FitPhase({
  signalQuality,
  isReady,
  qualityDrop,
  returnPhase,
  onContinue,
}: {
  signalQuality?: Record<string, number>;
  isReady: boolean;
  qualityDrop: boolean;
  returnPhase: Phase | null;
  onContinue: () => void;
}) {
  return (
    <div className="space-y-4">
      {qualityDrop && (
        <div
          className="text-[12px] font-mono px-3 py-2"
          style={{
            color: "var(--status-bad)",
            border: "1px solid var(--status-bad)",
            background: "rgba(232, 72, 104, 0.1)",
          }}
        >
          Signal lost — adjust headband before continuing
        </div>
      )}
      <p
        className="text-[13px]"
        style={{ color: "var(--text-secondary)" }}
      >
        Adjust headband until sensors are green
      </p>
      <div className="grid grid-cols-4 gap-3">
        {CHANNEL_NAMES.map((name) => {
          const q = signalQuality?.[name] ?? 0;
          const good = q > 0.7;
          return (
            <div key={name} className="flex flex-col items-center gap-1">
              <div
                className="w-6 h-6 rounded-full"
                style={{
                  background: good ? CH_COLORS[name] : "var(--status-bad)",
                  opacity: good ? 1 : 0.4,
                  boxShadow: good ? `0 0 8px ${CH_COLORS[name]}` : "none",
                }}
              />
              <span
                className="text-[10px] font-mono"
                style={{ color: "var(--text-dim)" }}
              >
                {name}
              </span>
              <span
                className="text-[10px] font-mono"
                style={{ color: good ? "var(--text-secondary)" : "var(--text-dim)" }}
              >
                {Math.round(q * 100)}%
              </span>
            </div>
          );
        })}
      </div>
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
        {returnPhase ? "Continue" : "Start Calibration"}
      </button>
    </div>
  );
}

function TestPhase({
  phase,
  config,
  detected,
  crossTalk,
}: {
  phase: Phase;
  config: PhaseConfig;
  detected: number;
  crossTalk: string[];
}) {
  return (
    <div className="space-y-4">
      <p
        className="text-[13px]"
        style={{ color: "var(--text-secondary)" }}
      >
        {config.instruction} — {config.required} times
      </p>

      {/* Progress circles */}
      <div className="flex justify-center gap-3">
        {Array.from({ length: config.required }).map((_, i) => (
          <div
            key={i}
            className="w-8 h-8 rounded-full border-2 flex items-center justify-center"
            style={{
              borderColor: i < detected ? "var(--status-good)" : "var(--border)",
              background: i < detected ? "rgba(56, 232, 112, 0.15)" : "transparent",
            }}
          >
            {i < detected && (
              <span style={{ color: "var(--status-good)", fontSize: 14 }}>✓</span>
            )}
          </div>
        ))}
      </div>

      {/* Cross-talk warnings */}
      {crossTalk.length > 0 && (
        <div
          className="text-[11px] font-mono"
          style={{ color: "var(--status-warn)" }}
        >
          Cross-talk: {crossTalk.map((k) => k.replace(/_/g, " ")).join(", ")}
        </div>
      )}

      {/* Phase label */}
      <div
        className="text-[10px] font-mono uppercase tracking-wider text-center"
        style={{ color: "var(--text-dim)" }}
      >
        {config.label}
      </div>
    </div>
  );
}

function DonePhase({ results }: { results: Record<string, PhaseResult> }) {
  const phases = ["blink", "double_blink", "nod", "shake"] as const;
  const labels: Record<string, string> = {
    blink: "Single Blink",
    double_blink: "Double Blink",
    nod: "Nod Yes",
    shake: "Shake No",
  };

  return (
    <div className="space-y-3">
      <p
        className="text-[14px] text-center"
        style={{ color: "var(--status-good)" }}
      >
        Calibration Complete
      </p>
      <div className="space-y-1">
        {phases.map((p) => {
          const r = results[p];
          const ok = r && r.detected >= r.required;
          return (
            <div
              key={p}
              className="flex items-center justify-between text-[11px] font-mono"
            >
              <span style={{ color: "var(--text-secondary)" }}>
                {labels[p]}
              </span>
              <span
                style={{
                  color: ok
                    ? "var(--status-good)"
                    : r && r.detected > 0
                      ? "var(--status-warn)"
                      : "var(--status-bad)",
                }}
              >
                {r ? `${r.detected}/${r.required}` : "skipped"}
                {r && r.crossTalk.length > 0 && " ⚠"}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

**Step 2: Verify frontend builds**

Run: `cd frontend && pnpm build`
Expected: No errors.

**Step 3: Commit**

```bash
git add frontend/src/components/demo/CalibrationOverlay.tsx
git commit -m "feat: CalibrationOverlay component with 6-phase calibration flow"
```

---

### Task 6: Wire CalibrationOverlay into demo page

**Files:**
- Modify: `frontend/src/routes/demo.tsx`

**Step 1: Add imports, state, and overlay rendering**

In `frontend/src/routes/demo.tsx`:

**1a.** Add import (after line 14):

```typescript
import { CalibrationOverlay } from "../components/demo/CalibrationOverlay";
```

**1b.** Change the useSensorStream destructure (line 25):

From:
```typescript
  const { buffers, metricsRef, eventsRef, isConnected } = useSensorStream();
```

To:
```typescript
  const { buffers, metricsRef, eventsRef, isConnected, sendCommand } = useSensorStream();
```

**1c.** Add calibration state (after line 30):

```typescript
  const [calibrated, setCalibrated] = useState(false);

  // Reset calibration on disconnect
  useEffect(() => {
    if (!isConnected) setCalibrated(false);
  }, [isConnected]);
```

**1d.** Add overlay rendering right after the CommandArrow (after line 67, `<CommandArrow lastEvent={lastEvent} />`):

```tsx
      {/* Calibration overlay */}
      {isConnected && !calibrated && (
        <CalibrationOverlay
          headbandState={metrics?.headband}
          signalQuality={metrics?.eeg?.signal_quality}
          lastEvent={lastEvent}
          sendCommand={sendCommand}
          onComplete={() => setCalibrated(true)}
        />
      )}
```

**Step 2: Verify frontend builds**

Run: `cd frontend && pnpm build`
Expected: No errors.

**Step 3: Commit**

```bash
git add frontend/src/routes/demo.tsx
git commit -m "feat: wire CalibrationOverlay into demo page"
```

---

### Task 7: Run full test suite + manual verification

**Files:**
- No new files.

**Step 1: Run backend tests**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

**Step 2: Run frontend build**

Run: `cd frontend && pnpm build`
Expected: No errors.

**Step 3: Manual verification guide**

Start backend: `python -m backend.main --synthetic`
Start frontend: `cd frontend && pnpm dev`
Open browser: `http://localhost:5173/demo`

Verify:
1. CalibrationOverlay appears on connect (z-40 overlay)
2. Fit phase shows 4 channel dots with quality %
3. Continue button works → advances to blink phase
4. Skip button dismisses overlay at any phase
5. Test phases show circles that fill on events
6. Done phase shows summary
7. After completion, overlay dismisses, demo page works normally
8. Disconnect → reconnect → overlay reappears
9. Check backend logs for "Calibrated: threshold_sd=..." when calibration completes
10. Low-confidence events are dimmed in EventLog

**Step 4: Commit all remaining changes**

```bash
git add -A
git commit -m "feat: fitting & calibration protocol — complete implementation"
```
