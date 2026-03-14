# Blink Detector Signal Processing — Deep Dive

Every step, every formula, every reason. Written to help us find where the design breaks down.

## 1. Data Flow: Hardware → Detection

```
Muse 2  →  BrainFlow SDK  →  EEGServer._stream_loop()  →  Pipeline.run(FAST)
   │          board_id=38         polling at ~60 fps          SpeechDetector
   │          256 Hz EEG          get_eeg_data() returns      BlinkDetector
   │          4 channels           shape (4, N) array           NodDetector
   │          µV units            typically N = 4 samples
   └─ BLE
```

**Chunk size**: Muse 2 sends data at 256 Hz. BrainFlow buffers it internally.
`get_eeg_data()` retrieves whatever's accumulated since last call.
At the server's `eeg_batch_interval` (~16ms, ~60fps), each call typically returns
**4 samples** (256 Hz × 0.016s ≈ 4). Sometimes 0, 8, or 12 depending on timing jitter.

**Channel layout**:
```
Index 0: TP9  (left temporal)
Index 1: AF7  (left frontal)
Index 2: AF8  (right frontal)
Index 3: TP10 (right temporal)
```

**Units**: All values in µV (microvolts). MNE .fif files store volts (multiply by 1e-6).

## 2. Signal Derivations (computed per chunk in `process()`)

```python
af7 = frame.eeg[1].astype(np.float64)     # left frontal, shape (N,)
af8 = frame.eeg[2].astype(np.float64)     # right frontal, shape (N,)
frontal = (af7 + af8) / 2.0               # average of both frontal channels
temporal = (frame.eeg[0] + frame.eeg[3]) / 2.0  # average of both temporal channels
```

**Why average?** Blinks produce a large negative EOG artifact on BOTH frontal channels.
Averaging improves SNR by √2 and is the signal used for shape validation.

**Per-channel means** (computed separately):
```python
af7_mean = float(np.mean(af7))   # mean of ~4 samples
af8_mean = float(np.mean(af8))   # mean of ~4 samples
chunk_val = (af7_mean + af8_mean) / 2.0  # combined frontal mean
```

## 3. Baseline Tracking

The detector maintains three sets of baselines, each updated differently.

### 3a. Combined Baseline (`_baseline_median`, `_baseline_mad`)

**Storage**: `_baseline_window` = deque(maxlen=256) of chunk means.
At ~64 chunks/sec (256 Hz / 4 samples), this holds ~4 seconds of data.

**Update rule**:
```python
_baseline_window.append(chunk_mean)
if len(_baseline_window) >= 8:
    _baseline_median = np.median(_baseline_window)
    _baseline_mad = np.median(np.abs(_baseline_window - _baseline_median))
    if _baseline_mad < 0.5:
        _baseline_mad = 0.5  # floor prevents zero-MAD
```

**Contamination guard**:
- Cold start (samples < 64): Accept everything into baseline
- Cold start (64 ≤ samples < 128): Accept if `|chunk_mean - median| < 5 × robust_sd`
- Warm (samples ≥ 128): Accept if `|chunk_mean - median| < 3 × robust_sd`
  where `robust_sd = 1.4826 × MAD`

**Why 1.4826?** This is the consistency constant that converts MAD to an equivalent
standard deviation for normally distributed data: `σ = 1.4826 × MAD`.

**Purpose**: The combined baseline is used for:
- Debug logging of deflections
- Calibration capture calculations
- Shape validation (secondary peak check)
- NOT used for threshold detection (per-channel baselines handle that)

### 3b. Per-Channel Baselines (`_af7_baseline_*`, `_af8_baseline_*`)

**Storage**: Separate deque(maxlen=256) and median/MAD for each channel.

**Update rule** (same for both channels):
```python
ch_median = current channel median
ch_mad = current channel MAD
robust_sd = 1.4826 × ch_mad

# Accept if: not enough data yet, OR robust_sd is near zero, OR within 3 SDs
if len(window) < 8 or robust_sd < 1e-6 or |ch_mean - ch_median| < 3 × robust_sd:
    window.append(ch_mean)
    # Recompute median/MAD if window has ≥8 entries
```

**Purpose**: Used by `_is_candidate()` for per-channel threshold crossing detection.
This allows detection when only one electrode has good contact (asymmetric fit).

### 3c. Temporal HF Baseline (`_temporal_hf_baseline`)

**NEW in current code**. Tracks the rolling baseline of temporal channel high-frequency energy.

**Storage**: `_temporal_hf_history` = deque(maxlen=128) of per-chunk HF RMS values.

**Update per chunk**:
```python
t_hf_chunk = _hf_rms(temporal)   # sqrt(mean(diff(temporal)^2))
_temporal_hf_history.append(t_hf_chunk)
if len(_temporal_hf_history) >= 16:
    _temporal_hf_baseline = np.median(_temporal_hf_history)
```

**`_hf_rms` formula**: First-order difference RMS
```python
def _hf_rms(sig):
    return sqrt(mean(diff(sig)^2))
```
For a 4-sample chunk `[a, b, c, d]`:
- `diff = [b-a, c-b, d-c]` (3 values)
- `_hf_rms = sqrt(mean([(b-a)², (c-b)², (d-c)²]))`

This approximates high-frequency energy. Smooth signals (slow drift, blink downstroke)
have small diffs → low HF. Noisy signals (muscle EMG, electrode artifact) have large
diffs → high HF.

**Purpose**: Used by the clench guard (Guard 1) to detect when temporal HF is elevated
ABOVE its own normal level (clench/speech EMG), rather than comparing against frontal HF
which drops during smooth blink deflections.

### ⚠️ BUG/ISSUE: Temporal HF baseline tracks ALL temporal HF values

The deque unconditionally appends every chunk. During sustained speech or jaw clenching
(>2 seconds), the elevated temporal HF values fill the history, shifting the baseline UP.
After 128 chunks (~2s), the baseline equals the elevated level, making `t_hf/baseline ≈ 1.0`.

**Consequence**: Sustained EMG lasting >2s will NOT be caught by the clench guard.
The speech detector (Guard 2) is the only defense for sustained speech, but it requires
`min_active_frac × window_chunks` = 0.4 × 48 = 19 chunks (~300ms) of temporal HF > 15 µV.

### ⚠️ BUG: No frontal HF baseline exists

The OLD clench guard compared `t_hf / f_hf` (temporal vs frontal HF). This had a side
effect: it rejected events where frontal HF was abnormally LOW at the trailing edge (slow
drifts, eye movements). These are legitimate FPs that the new guard doesn't catch.

The new guard only compares temporal HF to its own baseline. If temporal HF is normal but
frontal HF is suppressed (smooth drift), the new guard sees ratio ≈ 1.0 and does nothing.

**Impact**: Talk FP rate jumped from 0.23 → 0.46, rest FP from ~0.35 → 0.46,
750s baseline from ~7/min → 9/min.

## 4. Cold Start

**Counter**: `_baseline_samples` incremented by `n_samples` (chunk length) each accepted update.

**Gate**: `_is_candidate()` returns False when `_baseline_samples < 128`.
At 4 samples/chunk, this is ~32 chunks = ~0.5 seconds.

**Why 128?** Chosen to give enough data for the median/MAD to stabilize. With 256 Hz,
128 samples = 0.5s. This covers several blink-free intervals to establish a clean baseline.

**Problem**: The per-channel baselines don't use `_baseline_samples` for their own gating.
They use `len(window) >= 8` independently. So per-channel baselines can be "ready" in just
8 chunks (~125ms), while the cold-start gate requires 128 samples (~0.5s). They're consistent
because `_update_channel_baselines` doesn't increment `_baseline_samples`.

## 5. Threshold Detection: `_is_candidate(af7_mean, af8_mean)`

**Called per chunk** after baseline updates. Returns True if EITHER channel crosses
its adaptive threshold.

**Per-channel formula**:
```
robust_sd = 1.4826 × ch_MAD
adaptive_thresh = ch_median - threshold_sd × robust_sd

If threshold_uv > -9000 (calibrated floor is set):
    effective_thresh = max(adaptive_thresh, threshold_uv)
    // "max" picks the LESS negative → more permissive of the two
Else:
    effective_thresh = adaptive_thresh

crossed = ch_mean < effective_thresh
```

**The `max()` semantics**: Since blink values are negative:
- `adaptive_thresh` might be -45 µV (data must go below -45 to trigger)
- `threshold_uv` might be -35 µV (calibrated half-amplitude)
- `max(-45, -35) = -35` → uses the LESS deep threshold
- This makes detection EASIER when the adaptive threshold is too deep

**threshold_uv role**: It's a ceiling that prevents the effective threshold from becoming
too restrictive in high-noise sessions. Only activates when `adaptive_thresh < threshold_uv`
(i.e., noise is high, making the adaptive threshold very deep).

**OR gate**: `AF7 crossed OR AF8 crossed`. This means a blink is detected even if only
one electrode has good contact (common with dry electrodes and asymmetric fit).

### Typical values

For a resting session with median=-25µV, MAD=3.4µV:
```
robust_sd = 1.4826 × 3.4 = 5.04 µV
adaptive_thresh = -25 - 1.5 × 5.04 = -32.6 µV

A blink with chunk_mean = -45 µV → -45 < -32.6 → crossed = True ✓
Normal noise chunk_mean = -28 µV → -28 < -32.6? No → crossed = False ✓
```

For a noisy session with median=-25µV, MAD=8.0µV:
```
robust_sd = 1.4826 × 8.0 = 11.86 µV
adaptive_thresh = -25 - 1.5 × 11.86 = -42.8 µV

A weak blink chunk_mean = -35 µV → -35 < -42.8? No → MISSED ✗
If threshold_uv = -30 (calibrated):
    effective_thresh = max(-42.8, -30) = -30 µV
    -35 < -30 → crossed = True ✓
```

### ⚠️ ISSUE: threshold_sd sensitivity

`threshold_sd = 1.5` means "1.5 robust SDs below median". This is VERY sensitive:
- For Gaussian noise, 1.5σ below mean captures 6.7% of samples
- Our 4-sample chunk means have LOWER variance than individual samples (by √4 = 2x)
- So the effective threshold is actually 1.5 × 2 = 3.0 SD in individual-sample terms
- At 3.0σ, false crossing probability per chunk ≈ 0.13% (1 in 770)
- At 64 chunks/second, that's ~5 false crossings per minute

This is why we need robust GUARDS after threshold detection — the threshold alone
is too sensitive by design (to catch weak blinks).

## 6. Sustained Deflection: Trailing-Edge Detection

**State**: `_consecutive_crossed` counter.

**Logic per chunk**:
```python
if crossed:
    _consecutive_crossed += 1
else:
    if _consecutive_crossed > 0:
        streak = _consecutive_crossed
        _consecutive_crossed = 0
        min_chunks = max(2, int(min_deflection_ms / 1000 * 256 / chunk_length))
        if streak >= min_chunks:
            _try_emit_blink(frame, now)  # run all guards
```

**min_chunks formula**:
```
min_chunks = max(2, floor(min_deflection_ms ÷ 1000 × 256 ÷ 4))
           = max(2, floor(50 ÷ 1000 × 256 ÷ 4))
           = max(2, floor(3.2))
           = max(2, 3)
           = 3
```
So a blink must cross the threshold for at least 3 consecutive 4-sample chunks (12 samples = ~47ms).

**Why trailing edge?** We WAIT until the crossing streak ENDS before validating. This ensures:
1. The full blink waveform is in the buffer (not just the leading edge)
2. Shape validation can see the complete V-shape (both downstroke and upstroke)
3. Duration is known (streak × chunk_size = deflection duration)

**Why not leading edge?** The leading edge only tells us the signal went below threshold.
We don't know the shape yet — it could be a slow drift, a one-sample spike, or a real blink.
The trailing edge tells us the complete story.

### ⚠️ BUG FOUND AND FIXED (previous session): Bilateral floor

Previously, `bilateral_floor_uv = -12.0` was an absolute threshold: if EITHER channel's
mean was below -12µV, `crossed = True`. But for sessions with baseline at -30µV (common!),
EVERY chunk was below -12µV, so `_consecutive_crossed` accumulated to thousands, and the
trailing edge was never reached. **Fix**: bilateral floor was removed entirely.

## 7. Guard Pipeline: `_try_emit_blink(frame, now)`

Called ONLY on trailing edge when streak ≥ min_chunks. Guards run in order;
first rejection exits the function (no event emitted).

### Guard 0: Motion Guard

```python
if gyro_pitch_peak > 20.0 or gyro_yaw_peak > 20.0:
    REJECT
```

**Input**: `frame.imu[4]` (gyro pitch) and `frame.imu[5]` (gyro yaw), peak absolute value.

**Threshold**: 20 deg/s. Head nods typically produce 40-150 deg/s, shakes 100-200 deg/s.
Subtle head movements during typing are 1-10 deg/s.

**When this fires**: Head nods and shakes cause low-frequency EEG artifacts that can
mimic blinks. The motion guard catches these.

**When it doesn't fire**: Blinks cause NO head movement. Eye movements cause NO head movement.

**Limitation**: Only checks the CURRENT frame's IMU data (typically 1-2 samples at 52Hz).
If the head movement happened 100ms earlier (during the blink-like artifact), the IMU data
in the current frame may not show it. This is the "frame timing lag" issue from git history.

### Guard 0.5: Bilateral Correlation (DISABLED)

```python
if self.min_bilateral_corr > 0:   # default 0.0 = disabled
```

**Why disabled**: Dry electrodes on Muse 2 produce highly variable contact quality.
AF7↔AF8 correlation for real blinks can be as low as 0.2 with poor contact on one side.

### Guard 1: Clench Guard (CURRENT — temporal-baseline comparison)

```python
win = min(128, buffer_length)
t_win = temporal_buf[last 'win' samples]
t_hf = _hf_rms(t_win)
temporal_baseline = max(_temporal_hf_baseline, 1.0)
hf_ratio = t_hf / temporal_baseline
effective_max = max_hf_ratio × (2.0 - frontal_quality)

if hf_ratio > effective_max:
    REJECT
```

**The `_hf_rms` over 128 samples**: Unlike the per-chunk HF (3 diff values from 4 samples),
this computes over 127 diff values, giving a much more stable estimate.

**Quality scaling**: `effective_max = 3.5 × (2.0 - 1.0) = 3.5` at full quality.
At quality=0.5: `3.5 × 1.5 = 5.25` (more permissive for poor fit).

### ⚠️ CRITICAL ISSUE: Guard 1 no longer catches talk/drift FPs

**Old guard** (removed): `hf_ratio = t_hf / f_hf` — temporal HF ÷ frontal HF.

During a trailing edge after a slow drift or talk-coincident deflection:
- Frontal HF is low (smooth recovery from deflection)
- Temporal HF is normal (no clench)
- Old: ratio = normal / low = HIGH → REJECTED (correct FP rejection)
- New: ratio = normal / normal_baseline = 1.0 → NOT rejected (FP passes through)

**Old guard problem** (why it was changed): During a REAL blink:
- Frontal HF is low (smooth V-shape downstroke/upstroke)
- Temporal HF is at its normal level
- Old: ratio = normal / low = HIGH → REJECTED (incorrect: real blink blocked!)

In the `blink_continuous` session, temporal channels had elevated electrode noise at baseline.
The old ratio was ALWAYS 8-10x, blocking 100% of blinks. This was the motivation for the change.

**The tradeoff**:
| Scenario | Old Guard (t_hf/f_hf) | New Guard (t_hf/t_baseline) |
|---|---|---|
| Real blink | BLOCKS (frontal HF low) ✗ | PASSES (temporal unchanged) ✓ |
| Jaw clench | BLOCKS (temporal HF high) ✓ | BLOCKS (temporal HF high) ✓ |
| Talk + deflection | BLOCKS (frontal HF low) ✓ | PASSES (temporal normal) ✗ |
| Slow drift | BLOCKS (frontal HF low) ✓ | PASSES (temporal normal) ✗ |
| Poor fit session | BLOCKS ALL (always high ratio) ✗ | PASSES (baseline absorbs noise) ✓ |

**We need BOTH behaviors**: Block clenches (temporal-baseline) AND block slow drifts (frontal-HF check).
But the old frontal-HF check also blocks real blinks, which is the original problem.

### Guard 2: Speech Guard

```python
speech = frame.get(SpeechResult)
if speech and speech.speech_active:
    REJECT
```

**SpeechDetector logic**:
```python
temporal = (TP9 + TP10) / 2.0
t_hf = _hf_rms(temporal)   # per-chunk, ~4 samples
_hf_history.append(t_hf)   # deque(maxlen=48) = ~750ms window

if len(_hf_history) >= 48:
    n_above = count(v > 15.0 for v in _hf_history)
    active = n_above >= 19  # 40% of 48 chunks
```

**When this fires**: When temporal HF RMS has been above 15µV for ≥300ms (19 of 48 chunks).
This catches sustained speech but NOT brief sounds or single words <300ms.

**Typical values**:
- Quiet rest: temporal HF RMS ≈ 5-10 µV/chunk → below 15 threshold
- Speech: temporal HF RMS ≈ 15-40 µV/chunk → above 15 threshold
- Jaw clench: temporal HF RMS ≈ 20-60 µV/chunk → above 15 threshold (but brief)

### Guard 3: Shape Validation (`_check_shape()`)

Uses the 512-sample circular buffer (`_frontal_buf`) to analyze the waveform shape.

**Step 1: Reconstruct ordered buffer**
```python
buf = concat(frontal_buf[buf_pos:], frontal_buf[:buf_pos])  # unwrap circular buffer
```

**Step 2: Find blink peak** (most negative point in buffer)
```python
min_idx = argmin(buf)
peak_val = buf[min_idx]
half_amp = peak_val / 2.0
```

### ⚠️ BUG: `half_amp` is computed as `peak_val / 2.0`, not relative to baseline

For a signal with baseline=-25µV and blink peak=-75µV:
- `half_amp = -75 / 2 = -37.5 µV`
- The TRUE half-amplitude should be `(-75 + -25) / 2 = -50 µV`
- The boundary search using -37.5 will find a WIDER region than intended
  (it searches until the signal rises above -37.5, which is ABOVE baseline)

For a signal with baseline near 0 µV, this doesn't matter. But for our recordings
with baseline at -20 to -80 µV, the half-amplitude calculation is incorrect.

**Impact**: Duration measurement is inflated → shapes may pass duration check
that shouldn't, or fail that should pass.

**Cascading effect on slope check**: The boundaries found using the wrong half_amp are
used to compute `blink_amplitude = abs(peak_val - mean([buf[left_idx], buf[right_idx]]))`.
With boundaries at the wrong level, `blink_amplitude` is SMALLER than the true value,
producing a smaller `min_slope`, making the slope check MORE PERMISSIVE than intended.

**Step 3: Find left/right boundaries at half-amplitude**
```python
# Walk left from peak until signal >= half_amp
for i in range(min_idx-1, -1, -1):
    if buf[i] >= half_amp: left_idx = i; break

# Walk right from peak until signal >= half_amp
for i in range(min_idx+1, len(buf)):
    if buf[i] >= half_amp: right_idx = i; break
```

**Step 4: Duration check**
```python
contiguous = right_idx - left_idx + 1
dur_ms = contiguous / 256.0 * 1000.0

if dur_ms < 50.0 ms: REJECT (too brief)
if dur_ms > 200.0 ms: REJECT (too broad)
```

Note: due to the half_amp bug above, this duration is measured at the wrong amplitude level.

**Step 5: Secondary peak check** (confidence booster, NOT a gate)
```python
# Check 150ms window after right boundary
after_right = buf[right_idx+1 : right_idx+40]
if max(after_right) > baseline_median + 2.0:
    secondary_peak = True  # adds 0.05 to confidence
```

**Step 6: R² tent fitting** (computed but NOT gated on)
```python
downstroke = buf[left_idx : min_idx+1]
upstroke = buf[min_idx : right_idx+1]

# Inner 80% linear regression
r2_down, slope_down = r_squared_and_slope(downstroke)
r2_up, slope_up = r_squared_and_slope(upstroke)
```

R² is NOT used as a gate because "4-sample streaming noise makes linear R² unreliable —
R²=0.7 rejected 32% of valid blinks".

**Step 7: Slope direction check** (IS a gate)
```python
blink_amplitude = abs(peak_val - mean([buf[left_idx], buf[right_idx]]))
if blink_amplitude > 1.0:
    min_slope = blink_amplitude × 0.15 / max(len(downstroke), len(upstroke))
    if slope_down > -min_slope or slope_up < min_slope:
        REJECT (plateau — slopes too flat)
```

This rejects events where both halves have near-zero slope (constant-level deflections,
not V-shaped blinks). A real blink has: downstroke slope < 0, upstroke slope > 0.

### Guard 4: Template Matching (DISABLED)

```python
if self._matched_filt is None or self.mf_threshold >= 0:
    return True  # disabled
```

**Why disabled**: "Template matching doesn't work on 4ch Muse — V-shape too generic,
NCC overlap is complete."

### Refractory Period

```python
elapsed_ms = (now - _last_blink_time) × 1000
if elapsed_ms < 100 ms:
    REJECT (too soon after last blink)
```

Prevents double-counting the same blink event.

## 8. Event Classification

After passing all guards, the blink candidate is added to `_pending_blinks`.
A classification window (`classify_window_ms = 600ms`) groups rapid blinks:

```python
# When window expires:
if count >= 2:
    emit "double_blink" (confidence = 0.85 + 0.05 if secondary_peak)
else:
    emit "single_blink" (confidence = 0.90 + 0.05 if secondary_peak)

# Confidence scaled by frontal quality:
final_confidence = base_confidence × frontal_quality
```

## 9. Calibration Flow

### Blink Capture (`start_blink_capture` → `get_capture_result`)

1. User clicks "calibrate" in UI
2. Backend opens a 0.7s capture window
3. All frontal samples during the window are collected (raw, no threshold)
4. After 0.7s, compute:
   ```
   peak_val = min(all_samples)  # deepest negative excursion
   half_amp = (peak_val + baseline_median) / 2.0
   ```
5. Result sent to frontend for the calibration overlay

### Threshold Calibration (`set_calibrated_threshold`)

Called with `median_peak_amplitude_uv` (median of several captured blink peaks):
```python
half_amp_uv = (median_peak_amplitude_uv + baseline_median) / 2.0
self.threshold_uv = half_amp_uv
# threshold_sd is NOT changed
```

**Previous bug (fixed)**: `set_calibrated_threshold` used to change `threshold_sd` to
`min(peak_sds × 0.5, 3.5)`. For stable low-MAD sessions, this RAISED threshold_sd (from 1.5
to 3.5), making the adaptive threshold deeper and harder to reach. Now threshold_sd is
left unchanged; only `threshold_uv` is set as a floor.

### Manual Threshold (`set_blink_threshold`)

From the UI slider. Sets `threshold_sd` and/or `threshold_uv` and/or `max_hf_ratio`.
When `threshold_sd` is changed, `threshold_uv` is cleared to -9999 (disabled) so the
adaptive threshold takes full control.

## 10. Sensitivity Slider Mapping (Frontend)

The UI slider maps a single sensitivity value (1-10) to both `threshold_sd` and `max_hf_ratio`:

```
Sensitivity 1  (max FP):   threshold_sd = 1.0,  max_hf_ratio = 99 (disabled)
Sensitivity 5  (middle):   threshold_sd = 2.6,  max_hf_ratio = 3.5
Sensitivity 10 (strict):   threshold_sd = 4.5,  max_hf_ratio = 2.0
```

The slider sends `{ cmd: "set_blink_threshold", threshold_sd, max_hf_ratio }` to backend.

## 11. Known Issues and Design Tensions

### Issue A: Clench guard tradeoff (CRITICAL — currently failing tests)

The old guard (`t_hf/f_hf > 3.5`) caught:
- Clenches ✓
- Talk-coincident deflections ✓ (via low frontal HF)
- Slow drifts ✓ (via low frontal HF)
- BUT ALSO real blinks ✗ (frontal HF is always low during smooth V-shape)

The new guard (`t_hf/t_hf_baseline > 3.5`) catches:
- Clenches ✓
- BUT NOT talk-coincident deflections ✗
- BUT NOT slow drifts ✗
- Real blinks pass through ✓ (temporal HF unchanged)

**Root cause**: Frontal HF drops during ANY smooth deflection — blinks, slow drifts,
and talk-coincident eye movements ALL produce smooth frontal signals. The old guard
couldn't distinguish them.

**Possible fixes**:
1. Track frontal HF baseline separately, reject when frontal HF is anomalously LOW
   (below 30% of its baseline = too smooth for normal EEG)
2. Use BOTH guards: temporal-baseline for clenches, and a frontal-baseline for slow drifts
3. Improve shape validation to catch slow drifts (they tend to be >200ms)
4. Accept the tradeoff: higher FP rate in exchange for not blocking ALL blinks in poor-fit sessions

### Issue B: `_check_shape` half-amplitude uses absolute values, not baseline-relative

`half_amp = peak_val / 2.0` instead of `(peak_val + baseline) / 2.0`.
When baseline is -30µV and peak is -80µV:
- Current: half_amp = -40µV (boundary search starts at -40)
- Correct: half_amp = (-80 + -30)/2 = -55µV

The boundaries are found where signal >= half_amp. With the current bug:
- Search finds where signal >= -40µV, which is ABOVE baseline (-30µV)!
- The left boundary is likely at the very edge of the buffer (before the blink region)
- This inflates the duration measurement

### Issue C: Temporal HF baseline has no contamination guard

The `_temporal_hf_history` deque accepts ALL values, including clench/speech periods.
After ~2s of sustained EMG, the baseline shifts up, making future clenches undetectable.

The combined frontal baseline has a contamination guard (reject chunks >3 SDs from median).
The temporal HF baseline has none.

### Issue D: Per-chunk HF RMS is very noisy

`_hf_rms` on a 4-sample chunk computes from just 3 diff values. The variance is enormous.
These per-chunk values feed `_temporal_hf_history`, whose median is more stable, but the
per-event window (128 samples in `_try_emit_blink`) is much more reliable.

Possible mismatch: the baseline (median of 128 noisy 4-sample HF values) may not
match the event-time HF (single stable 128-sample computation).

### Issue E: Talk FP rate doubled

Talk FP rate went from 0.23 → 0.46 after changing the clench guard.
Debug shows: speech guard catches many talk events, but not all. The clench guard
(both old and new) isn't catching the remaining ones — they pass with temporal HF
ratio ≈ 1.0 (temporal is at its baseline level during brief single-word speech).

These FPs are likely natural blinks that coincide with talk trials. The user blinks
naturally at 15-20/min, and talk trials are 5s long, so ~1-2 natural blinks per trial.
Previously, the buggy clench guard was accidentally suppressing these natural blinks
(because frontal HF drops during smooth blink V-shape).

### Issue F: `blink_continuous` protocol fires beat 0 at t=0

The metronome fires its first beat immediately when the trial starts (beat 0 at t=0s).
The user blinks at t=0, but the detector's baseline hasn't stabilized yet (cold start
requires 128 samples = 0.5s). Even if baseline IS stable from the rest period before,
the first blink contaminates it.

Fix: add `cueAt: 2` to the protocol and offset metronome start so beat 0 fires at t=2s.

## 12. Summary of All State Variables

| Variable | Type | Size | Purpose |
|---|---|---|---|
| `_baseline_window` | deque[float] | 256 | Combined frontal chunk means |
| `_baseline_median` | float | 1 | Median of combined baseline |
| `_baseline_mad` | float | 1 | MAD of combined baseline |
| `_baseline_samples` | int | 1 | Total samples processed (cold start counter) |
| `_af7_baseline_window` | deque[float] | 256 | AF7 per-channel means |
| `_af7_baseline_median` | float | 1 | AF7 channel median |
| `_af7_baseline_mad` | float | 1 | AF7 channel MAD |
| `_af8_baseline_*` | (same as AF7) | | AF8 channel stats |
| `_temporal_hf_history` | deque[float] | 128 | Per-chunk temporal HF RMS values |
| `_temporal_hf_baseline` | float | 1 | Median temporal HF (for clench guard) |
| `_frontal_buf` | ndarray | 512 | Circular buffer: frontal signal |
| `_temporal_buf` | ndarray | 512 | Circular buffer: temporal signal |
| `_af7_buf` | ndarray | 512 | Circular buffer: AF7 |
| `_af8_buf` | ndarray | 512 | Circular buffer: AF8 |
| `_buf_pos` | int | 1 | Write position in circular buffers |
| `_buf_filled` | bool | 1 | Whether buffers have wrapped |
| `_consecutive_crossed` | int | 1 | Current threshold-crossing streak |
| `_pending_blinks` | deque[tuple] | 10 | Blinks awaiting classification |
| `_classify_deadline` | float | 1 | When to emit classification |
| `_last_blink_time` | float | 1 | For refractory period |
| `_frontal_quality` | float | 1 | Signal quality (0-1, from features stage) |
| `threshold_sd` | float | 1 | SD multiplier for adaptive threshold |
| `threshold_uv` | float | 1 | Calibrated absolute floor (-9999=disabled) |
| `max_hf_ratio` | float | 1 | Clench guard ratio threshold |

## 13. Test Failure Root Causes

| Test | Old Value | New Value | Cause |
|---|---|---|---|
| test_talk_fp_rate | 0.23 | 0.46 | Natural blinks in talk trials now pass through (old guard accidentally blocked them via low frontal HF) |
| test_rest_fp_rate | ~0.35 | 0.46 | Same: natural blinks in rest trials now detected |
| test_fp_rate_750s_baseline | ~7/min | 9.04/min | Natural blinks now detected across 12.5-minute session |
| test_no_cold_start_burst | 0 events | 1 event at 4.15s | Blink at t=4.15s was previously suppressed by old guard |
| test_clench_fp_below_talk_fp | talk≤0.25 | talk=0.46 | Depends on talk_fp_rate |

## 14. Additional Findings from Verification

### Dead code: `baseline_alpha` parameter

`__init__` accepts `baseline_alpha: float = 0.01` (line 118) and stores it as
`self.baseline_alpha`, but **it is never referenced anywhere in the class**. Vestige
from an older EMA-based baseline approach replaced by the current median/MAD window.

### Frontend/backend default mismatch

- Backend default: `threshold_sd = 1.5` (detectors.py:117)
- Frontend default sensitivity = 4, which maps to `threshold_sd = 2.2` (DetectorControls.tsx:37)
- On first UI interaction, the slider sends SD=2.2 to a backend that started with SD=1.5
- Before any UI interaction, the backend runs at SD=1.5 (more sensitive than the UI default)

### SpeechDetector cold start

SpeechDetector only activates when its history deque is COMPLETELY full (48 chunks ≈ 750ms).
For the first ~750ms of a session, speech is never flagged active, even if temporal EMG is
clearly elevated. This creates a window where talk-coincident blink artifacts pass through.

### `_frontal_quality` update lag

`_frontal_quality` is set by `SignalQualityChecker` (a SLOW stage in `_metrics_loop`),
not by the FAST path. The metrics loop runs every ~500ms. So quality changes lag behind
the FAST event detection by up to 500ms. During transitions (headband adjustment, etc.),
the quality scaling on confidence and clench guard may be stale.

### `_baseline_samples` only counts ACCEPTED chunks

The cold-start counter `_baseline_samples` only increments when a chunk passes the
contamination guard. If many chunks are rejected during a noisy startup, the cold-start
gate (`< 128`) persists longer than expected. In extreme cases (continuous noise), the
detector may never exit cold start.

### min_chunks uses actual chunk length, not hardcoded 4

The formula in Section 6 shows `floor(50 / 1000 * 256 / 4) = 3`, but the actual code
uses `max(len(frontal), 1)` as the divisor, not a constant 4. For typical 4-sample
chunks this gives the same result, but for larger chunks (e.g., 8 or 12 from timing
jitter), `min_chunks` could be 2 instead of 3.
