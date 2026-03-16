# Fitting & Calibration Protocol — Design

## Problem

Blink amplitude varies 10-20x across sessions due to Muse 2 headband positioning. Office demo showed 5/7 sessions with POOR signal quality. The BlinkDetector's adaptive threshold (sd=1.5) fails when blinks are only 2-3 SDs from baseline (-12µV vs normal -50µV). No user guidance exists for achieving good fit, and the detector has no way to learn a person's blink characteristics.

## Solution

Two complementary approaches:

**A) CalibrationOverlay** — Frontend-driven 6-phase guided flow at connect time. Tests fit quality, collects blink profile (half-amplitude, slope, duration), verifies all commands work (blink, double blink, nod, shake), sends calibration data to backend.

**B) Quality-gated confidence** — BlinkDetector scales event confidence by real-time frontal signal quality. Frontend components gate actions on confidence threshold. Works independently of calibration — detector becomes smarter even without the overlay.

## Research Context

Cross-domain research (VR, EEG, fitness wearables, hearing aids) shows consistent patterns:
- **Muse's own app**: sensor check + 1-minute calibration + prescriptive fit instructions
- **Emotiv**: real-time per-electrode impedance display (green/yellow/red/black), quality gates EEG quality
- **Varjo VR**: progressive disclosure — "always calibrate / remember / best estimation"
- **Whoop**: stops transmitting RR-intervals during motion rather than sending bad data
- **Oura Ring**: 18-path LED selection adapts to fit automatically (hardware, not applicable to us)

Key insight: EEG is harder than PPG because electrical impedance varies 10-100x with contact, while optical signal varies 2-3x. Calibration is essential, not optional.

See `docs/research/2026-03-13-wearable-fitting-patterns.md` for full analysis.

---

## Backend Changes

### BlinkDetector: blink profile metadata

Each emitted blink event includes metadata for calibration and debugging:

```python
metadata={
    "amplitude_uv": peak_value,          # deepest deflection (most negative)
    "half_amplitude_uv": half_amp_value, # half-peak on downstroke — onset detection point
    "onset_slope": slope_down,           # downstroke slope — steeper = earlier detection
    "duration_ms": dur_ms,               # half-amplitude width
}
```

These are already computed in `_check_shape` — just need to pass them out instead of discarding.

### BlinkDetector: calibration method

```python
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

`threshold_uv` stays unused — the adaptive threshold (`median - threshold_sd * robust_sd`) is the only detection gate. Calibration tunes `threshold_sd`, the MAD baseline handles drift.

### BlinkDetector: quality-gated confidence

```python
def set_signal_quality(self, frontal_quality: float) -> None:
    """Update frontal signal quality (0-1). Scales event confidence."""
    self._frontal_quality = frontal_quality
```

When emitting events, confidence is scaled:
```python
confidence = base_confidence * self._frontal_quality
```

- Good fit (quality=1.0): confidence=0.90 (single), 0.85 (double)
- Poor fit (quality=0.3): confidence=0.27, 0.26

### No explicit rest phase

The fit check phase (waiting for headband "ready" = 3s good signal) doubles as baseline accumulation. By the time blink testing starts, the MAD baseline has settled.

### No hard floor

`threshold_uv` remains dead code. The adaptive threshold is the only gate. Can add a hard floor later if noise causes phantom detections.

---

## Server Changes (`main.py`)

### Broadcast event metadata

```python
# In the bci_event broadcast (line ~339):
await self._broadcast_text(json.dumps({
    "type": "bci_event",
    "kind": event.kind,
    "confidence": event.confidence,
    "channel": event.channel,
    "timestamp": event.timestamp,
    "metadata": event.metadata,  # NEW
}))
```

### `calibrate_blink` command

```python
def _get_blink_detector(self):
    for stage in self._pipeline.stages:
        if getattr(stage, 'name', None) == 'blink_detector':
            return stage
    return None

# In _handle_command:
elif action == "calibrate_blink":
    detector = self._get_blink_detector()
    if detector:
        detector.set_calibrated_threshold(
            median_half_amplitude_uv=cmd.get("median_half_amplitude_uv", -25.0),
        )
```

### Quality → detector bridge

In the metrics loop, after computing signal quality:

```python
sq = frame.get(SignalQualityResult)
if sq:
    detector = self._get_blink_detector()
    if detector:
        frontal_avg = (sq.quality.get("AF7", 0) + sq.quality.get("AF8", 0)) / 2
        detector.set_signal_quality(frontal_avg)
```

---

## Frontend Changes

### Protocol types (`protocol.ts`)

```typescript
export interface BciEvent {
  type: "bci_event";
  kind: string;
  confidence: number;
  timestamp: number;
  channel?: string;
  metadata?: Record<string, unknown>;  // NEW
}
```

### useSensorStream

Pass `metadata` through when constructing BciEvent from incoming JSON (already passes through if field exists, just needs the type).

### CalibrationOverlay component (new)

**Props:**
```typescript
{
  headbandState: { state: string; seconds_in_state: number } | undefined;
  signalQuality: Record<string, number> | undefined;
  lastEvent: BciEvent | null;
  sendCommand: (cmd: Record<string, unknown>) => void;
  onComplete: () => void;
}
```

**6 phases:**

#### Phase 1: FIT
- 4 large channel dots with labels + quality percentage
- "Adjust headband until sensors are green"
- [Continue] button — always enabled but dots guide the user
- [Skip All] button
- When headband state = "ready" (3s good signal), highlight Continue

#### Phase 2: BLINK (3 single blinks)
- "Blink naturally — 3 times"
- 3 empty circles → fill as `single_blink` events arrive
- Collect `metadata.half_amplitude_uv`, `metadata.onset_slope`, `metadata.duration_ms` from each
- 15s timeout → advance with whatever collected

#### Phase 3: DOUBLE BLINK (2 double blinks)
- "Blink twice quickly — 2 times"
- 2 circles fill on `double_blink` events
- Verifies classify window works for this person
- 15s timeout

#### Phase 4: NOD YES (2 nods)
- "Nod yes — 2 times"
- 2 circles fill on `nod_yes` events
- Cross-talk check: if `single_blink` fires during this phase → flag it
- 10s timeout

#### Phase 5: SHAKE NO (2 shakes)
- "Shake head no — 2 times"
- 2 circles fill on `nod_no` events
- Cross-talk check: same
- 10s timeout

#### Phase 6: DONE
- Summary: which commands verified, blink profile stats
- Send `calibrate_blink` command with median half_amplitude, duration, slope
- Auto-dismiss after 2s via `onComplete()`

**Quality drop handling:**
- Monitor frontal quality (AF7+AF8 avg) during phases 2-5
- If drops below 0.5: pause current phase, show "Signal lost — adjust headband"
- Discard current phase's collected data
- Return to fit phase
- After re-fitting, restart the interrupted phase

### Confidence gating in existing components

| Component | Gate | Below threshold behavior |
|-----------|------|--------------------------|
| BlinkFlash | confidence > 0.6 | Don't flash |
| CommandArrow | confidence > 0.6 | Don't show arrow |
| KioskPlayer | confidence > 0.6 | Don't send playback command |
| EventLog | none (show all) | Dim: opacity 0.4, muted color |

### Demo page wiring

```typescript
const { sendCommand } = useSensorStream();
const [calibrated, setCalibrated] = useState(false);

// Reset on disconnect
useEffect(() => {
  if (!isConnected) setCalibrated(false);
}, [isConnected]);

// Render overlay
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

---

## Edge Cases

- **Double blink during blink phase** → count as blinks, use the amplitude
- **Blink during nod/shake phase** → flag as cross-talk, show in summary
- **Very weak blinks (half_amp > -10µV)** → calibrate anyway, confidence gating will handle downstream
- **No blinks detected in 15s** → advance, show "single blink: not detected" in summary
- **Disconnect during calibration** → `calibrated` resets, overlay reappears on reconnect
- **Quality drop mid-phase** → pause, return to fit, discard partial data, restart phase
- **Skip All** → no calibration, detector uses defaults + quality-gated confidence still works
- **Future relaxation** → quality drop threshold (0.5) and fit requirements can be relaxed based on real usage data

## Verification

1. Start backend with `--synthetic`, connect frontend
2. Overlay appears showing fit phase (synthetic = always "good" signal)
3. After clicking Continue → blink phase
4. Blink 3 times → circles fill, advance to double blink
5. Complete all phases → "Done" summary, overlay dismisses
6. Check backend logs for "Calibrated: threshold_sd=..."
7. Skip All button dismisses overlay at any phase
8. Disconnect/reconnect → overlay reappears
9. Poor signal quality → low-confidence events → BlinkFlash doesn't fire, EventLog dims them
