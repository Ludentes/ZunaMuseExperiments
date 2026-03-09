# Muse 2 Detector Development: Lessons Learned

**Date:** 2026-03-09
**Based on:** 93 recorded trials, 5 detector iterations, ~20 approaches tested

---

## The Core Problem

Muse 2 has 4 channels: TP9 (left temporal), AF7 (left frontal), AF8 (right frontal), TP10 (right temporal). The frontal pair sits above the eyes; the temporal pair sits behind the ears near jaw muscles. Every signal of interest shares bandwidth and spatial overlap with artifacts from other sources. Blinks, clenches, speech, and eye movements all produce large deflections on overlapping channels and frequency ranges.

## What Works

### 1. Buffer-based features, not per-chunk features

The single most important lesson. BrainFlow delivers ~4 samples per frame at 256Hz. Any feature computed on 4 samples is dominated by noise. Features that cleanly separate conditions on full trials (kurtosis, correlation, asymmetry, HF ratio) become useless on 4-sample windows.

**The fix:** Accumulate a rolling buffer (128–512 samples) and compute features on that. The HF ratio guard went from 20/20 clench false positives (4-sample window) to 1/20 (128-sample window). Shape validation needs the full blink waveform in buffer (~100 samples) to measure duration.

**Rule of thumb:** Any feature that works well in a paper but uses "a 200ms window" needs at least 50 samples. If you're streaming at 4 samples/frame, you need 13 frames of history. Build the buffer first, then the feature.

### 2. Multi-layer guards with independent rejection criteria

No single feature separates all conditions. Each guard handles one confusion pair:

| Guard | Rejects | Mechanism | Window |
|---|---|---|---|
| Amplitude threshold | noise/rest | frontal (AF7+AF8)/2 < -75µV | per-chunk (4 samples) |
| Adaptive threshold | drift | EMA baseline ± 4 SD | rolling (256+ samples) |
| HF ratio | clenches | temporal_hf / frontal_hf > 3.5 | buffer (128 samples) |
| Speech fusion | speech | sustained temporal HF > 15 for 40%+ of 768ms window | rolling (48 chunks) |
| Shape validation | broad artifacts | contiguous deflection duration > 200ms | buffer (512 samples) |
| Refractory period | double-counting | 300ms minimum between detections | timestamp |

Each guard is cheap (<1ms) and independently testable. Adding a guard never makes recall worse by more than 2–3% if tuned correctly.

### 3. Temporal channels as artifact indicators

TP9/TP10 sit over the temporalis muscle. Jaw clenches produce 3.7–5.0× more high-frequency energy on temporal vs frontal channels. Blinks produce 1.1–3.3×. This is the single cleanest discriminator between blinks and clenches on Muse 2.

Speech also elevates temporal HF, but in a sustained pattern (hundreds of ms) vs the brief burst of a blink. The SpeechDetector exploits this temporal persistence.

### 4. Shape duration as a discriminator

Blink deflections are brief (30–170ms below half-peak amplitude). Speech artifacts are broader (200–312ms). A 200ms duration threshold rejects speech artifacts that pass all other guards. This requires buffering the full frontal waveform and finding the deepest point, then walking outward to measure contiguous duration.

### 5. EMA-based adaptive baseline

Electrode impedance drifts over minutes. A fixed -75µV threshold works initially but fails after the baseline shifts. An exponential moving average (alpha=0.001, ~4-minute time constant) tracks the baseline mean and variance. The threshold becomes `baseline_mean - 4 * SD`. Only updates during non-event periods to avoid blink artifacts corrupting the baseline.

Cold start: accumulate the first 256 samples (~1s) with a running average before switching to EMA.

## What Doesn't Work

### 1. Template matching / matched filter

Built a 102-sample averaged blink template from 18 recordings. Tested both raw convolution and normalized cross-correlation (NCC).

**Why it fails:**
- The blink V-shape is not unique. Talk, baseline drift, and electrode motion produce similar frontal deflections.
- NCC distributions overlap completely: blinks -0.57 to -0.85, talk -0.68 to -0.90, rest -0.76 to -0.87.
- In streaming, the buffer contains only a few blink samples when the threshold first triggers. The full waveform hasn't arrived yet, so the matched filter sees mostly noise.
- Would need spatial discrimination (8+ channels) or phase/timing features that the template can't capture on 4 channels.

**Verdict:** Don't bother with template matching on 4-channel consumer EEG unless you have a much more distinctive waveform (e.g., P300 on parietal channels, which Muse doesn't have).

### 2. Per-chunk statistics

Tested on 4-sample streaming chunks:
- **Kurtosis:** kills double-blink trials (two peaks = low kurtosis). Needs per-event thresholds that defeat the purpose.
- **AF7-AF8 correlation:** some real blinks have bilateral correlation as low as -0.13. Useless.
- **Frontal/temporal amplitude ratio:** blinks 0.22–1.0, talk 0.56–0.95. Complete overlap.
- **Rise/fall asymmetry ratio:** blinks 0.29–2.67, overlaps with everything.

### 3. Spatial methods

- **ICA:** needs 8+ channels minimum. 4 channels = 4 components, no degrees of freedom for separation.
- **CSP (Common Spatial Patterns):** marginally useful for concentration/relaxation with calibration, but not for event detection.
- **Spatial filtering:** with only 2 frontal + 2 temporal, there's no meaningful spatial pattern to exploit. Blinks are bilateral, clenches are bilateral, speech is bilateral.

### 4. Temporal channel gating

"Reject if temporal channels also cross threshold." Failed completely — blink artifacts propagate to temporal channels. A strong blink at -900µV on frontal produces -600µV on temporal. This rejects all blinks.

### 5. Smoothing / low-pass pre-filtering

Moving average (50–100ms) to remove EMG before threshold detection. Clench deflections are broadband enough to survive. Best F1=0.70. Made everything worse.

## Muse 2 Hardware Peculiarities

### Signal characteristics

- **EEG RMS:** 30–50 µV normal resting (eyes open). Lower than medical-grade but sufficient.
- **Blink amplitude:** -72 to -917 µV (single), up to -1000 µV (double). Extremely variable between blinks and sessions.
- **Clench amplitude:** -116 to -249 µV on frontal. Overlaps with gentle blinks — amplitude alone can't separate them.
- **Talk amplitude:** -51 to -636 µV on frontal. Some talk artifacts are indistinguishable from blinks on amplitude.
- **ADC saturation:** clips at ±1000 µV. Strong double blinks frequently hit the rail.

### Channel layout matters

- AF7/AF8 are best for blink detection (closest to eyes, strongest EOG component)
- TP9/TP10 are best for clench/speech detection (closest to temporalis/masseter muscles)
- Using frontal for detection and temporal for artifact rejection is the key architectural insight

### Band power estimation

- 2-second PSD windows are noisy. Values fluctuate 2–5× between consecutive estimates.
- Need 4–8 second rolling windows + exponential smoothing for anything user-facing.
- Alpha (8–13Hz) is the most reliable band. Eyes-closed alpha increase is the gold standard sanity check.
- Delta/theta on temporal channels spike with jaw artifacts — not reliable without artifact rejection.

### PPG / heart rate

- PPG needs ~1024 samples (16s at 64Hz) before BrainFlow's `get_heart_rate` works.
- HR accuracy is ±5–15 bpm vs chest strap. Acceptable for trends, not clinical use.
- SpO2 is unreliable on the forehead sensor. Don't display it.
- HRV (RMSSD) is broken with current naïve peak detection. Needs Pan-Tompkins or `heartpy`.

### IMU

- Accelerometer reports in g's (GRAVITY=1.0), not m/s².
- Head motion > 0.3g deviation from gravity indicates motion artifacts.
- Gyro is noisy but usable for head nod/shake detection.

## Design Principles for Future Detectors

1. **Buffer first, detect second.** Never compute features on raw 4-sample chunks. Accumulate 128+ samples, then apply your feature. The buffer is cheap; the false positives from noisy features are expensive.

2. **Use temporal channels for what they're good at:** artifact characterization, not primary detection. Frontal channels detect events; temporal channels validate or reject them.

3. **Stack cheap guards.** Each guard adds <1ms latency and handles one confusion pair. Five guards at 1ms each = 5ms total, F1=0.95. One complex classifier at 10ms = harder to debug and tune.

4. **Adaptive baselines are essential** for any session longer than 5 minutes. Electrode impedance drifts, skin moisture changes, the headband shifts. A fixed threshold that works at minute 1 fails at minute 30.

5. **Test on streaming, not batch.** A feature that separates conditions perfectly on full 3-second trials may be useless when computed on 4-sample chunks arriving every 16ms. The eval harness must simulate streaming.

6. **Document blind alleys.** We tested ~20 approaches. Most failed. The failures are as valuable as the successes — they prevent re-exploration. Record the approach, the data, and the specific reason it didn't work.

7. **Record diverse negative examples.** Clench and talk data were essential for reducing false positives. Rest-only testing gives inflated F1. Future detectors need: rest, target gesture, every plausible confusion gesture, baseline typing/working.
