# Blink Detection on Muse 2: Evaluation & Architecture

**Date:** 2026-03-09
**Data:** 93 recorded trials (20 rest, 20 single_blink, 20 double_blink, 20 clench, 13 talk)

---

## Executive Summary

Simple amplitude threshold on frontal channels (AF7+AF8) detects blinks well but cannot distinguish them from jaw clench or speech artifacts. The final five-layer detector — adaptive threshold + clench EMG guard + speech fusion + shape validation — achieves F1=0.91 (P=0.90, R=0.93) on recorded data with only 4 false positives across 53 negative trials.

## Signal Characteristics by Condition

| Condition | Frontal min (µV) | Temporal min (µV) | HF ratio (t/f) |
|---|---|---|---|
| rest | -44 to -104 (mean -58) | -104 | — |
| single_blink | -72 to -917 (mean -338) | -634 | 1.3–3.3 |
| double_blink | -305 to -1000 (mean -949) | -978 | 1.1–2.0 |
| clench | -116 to -249 (mean -154) | -410 | **3.7–5.0** |
| talk | -51 to -636 (mean -211) | -282 | 1.7–3.7 |

**Key insight:** Clench has uniquely high temporal/frontal HF ratio (3.7+). Talk overlaps with blinks on all simple features.

## Approaches Tested

### 1. Pure Amplitude Threshold

Sweep of threshold on frontal (AF7+AF8)/2 minimum:

| Threshold (µV) | P | R | F1 | FP rest | FP clench | FP talk |
|---|---|---|---|---|---|---|
| -50 | 0.47 | 0.93 | 0.62 | 12 | 19 | 11 |
| -75 | 0.58 | 0.95 | 0.72 | 1 | 20 | 7 |
| -100 | 0.58 | 0.95 | 0.72 | 1 | 20 | 7 |
| -150 | 0.73 | 0.82 | 0.78 | 0 | 8 | 4 |
| -200 | 0.86 | 0.78 | 0.82 | 0 | 1 | 4 |

**Verdict:** Clench is the dominant FP source. No threshold cleanly separates blinks from clenches because clench EMG propagates to frontal channels at -116 to -249µV, overlapping with gentle blinks.

### 2. Temporal Guard (rejected)

Reject if temporal channels ALSO cross threshold. **Failed:** blink artifacts propagate to temporal channels too, so this rejects all blinks.

### 3. Minimum Duration Filter (partially effective)

Measured duration of sub-threshold crossings:
- Blinks: median 74ms, mean 72ms (sustained negative deflection)
- Clenches: median 8ms, mean 16ms (brief EMG spikes)
- Talk: median 25ms, mean 53ms (in between)

A 40ms minimum duration rejects many clench spikes but not all (some last up to 109ms). Combined with threshold: F1=0.82 at best.

### 4. Smoothing / Low-pass (rejected)

Moving average (50-100ms window) to remove EMG. **Failed:** clench deflections are broadband enough to survive smoothing. Best F1=0.70.

### 5. HF Energy Ratio Guard (effective for clenches)

`_hf_rms(temporal) / _hf_rms(frontal)` — RMS of first-order diff approximates high-freq content.

Clenches produce much higher HF energy on temporal (jaw muscles) vs frontal. Blinks don't.

| Config | P | R | F1 |
|---|---|---|---|
| thresh=-75, no guard | 0.58 | 0.95 | 0.72 |
| thresh=-75, max_hf_ratio=3.5 | 0.83 | 0.97 | **0.90** |

**Eliminates all clench FPs.** Remaining FPs: 1 rest, 7 talk.

### 6. Sustained EMG Guard / Speech Fusion (effective for talk)

Speech produces sustained temporal HF energy (hundreds of ms). Blink HF is brief.

**SpeechDetector:** rolling window of per-chunk temporal HF RMS values. If enough chunks exceed threshold, flags `speech_active`.

Best parameters (grid search): `hf_thresh=15, min_active_frac=0.4, window=48 chunks (768ms)`

| Config | P | R | F1 | FP rest | FP clench | FP talk |
|---|---|---|---|---|---|---|
| HF guard only | 0.83 | 0.97 | 0.90 | 1 | 0 | 7 |
| HF guard + speech fusion | 0.85 | 0.97 | **0.91** | 1 | 2 | 4 |

**Reduces talk FPs from 7→4** with minimal recall loss.

### 7. Wide/Narrow HF Window Ratio (promising, not implemented)

For offline analysis with lookahead: compare HF RMS in narrow (±50ms) vs wide (±500ms) window around the event.

- Blinks: ratio 0.39-0.63 (HF concentrated around event)
- Talk: ratio 0.55-0.98 (HF sustained)

Threshold at 0.65 separates well but **requires ±500ms lookahead**, not feasible for real-time detection without added latency.

## Approaches NOT Effective on 4-Channel Muse

- **ICA/source separation:** needs 8+ channels minimum
- **Spatial patterns:** with only 2 frontal + 2 temporal, spatial resolution is too low to exploit blink topography
- **Pre-event temporal RMS:** blinks and speech both cause temporal elevation, ratio doesn't discriminate

## Final Architecture

```
SpeechDetector (FAST) → SpeechResult.speech_active
BlinkDetector (FAST):
  1. Frontal (AF7+AF8)/2 min < -75µV?
  2. HF ratio guard: temporal_hf/frontal_hf < 3.5? (rejects clenches)
  3. Speech guard: speech_active == False? (rejects talk artifacts)
  4. Refractory: 300ms since last blink?
  → Record pending blink
  5. After 800ms classify window: emit single/double/triple_blink
```

## Remaining FPs (4 talk trials)

These talk trials produce large, low-frequency frontal deflections (up to -636µV) with low temporal HF — indistinguishable from blinks with current features. Further reduction would require:
- Template matching against canonical blink waveform shape
- Lightweight ML classifier on short waveform snippets
- Or simply accepting that blink detection is unreliable during speech

## Evolution of Detector Versions

| Version | Layers | P | R | F1 | FP rest | FP clench | FP talk |
|---|---|---|---|---|---|---|---|
| v1 | amplitude -100µV | 0.58 | 0.95 | 0.72 | 1 | 20 | 7 |
| v2 | + HF ratio guard | 0.83 | 0.97 | 0.90 | 1 | 0 | 7 |
| v3 | + speech fusion | 0.85 | 0.97 | 0.91 | 1 | 2 | 4 |
| v4 | + adaptive thresh + shape | 0.90 | 0.93 | 0.91 | 1 | 1 | 2 |
| **v5** | **+ wide HF window + speech** | **0.95** | **0.95** | **0.95** | **0** | **1** | **1** |

## Phase 1 Implementation (v4)

Added to BlinkDetector:
1. **Adaptive threshold** — EMA baseline (alpha=0.001) with 4.0 SD threshold. Falls back to fixed -75µV during cold start (<256 samples). Baseline only updates during non-event periods.
2. **Shape validation** — rolling 512-sample frontal buffer. On threshold crossing, measures contiguous duration below half-peak amplitude. Rejects if > 200ms (speech artifacts are broader). Blinks: 30-170ms. Speech: 200-312ms.

## Phase 2: Template Matching (FAILED) + Wide HF Window (v5)

### Template matching / matched filter — ineffective on 4ch Muse

Built averaged blink template from 18 single_blink recordings (102 samples, saved to `blink_template.npy`). Tested both raw convolution (matched filter) and normalized cross-correlation (NCC).

**Results:**
- Raw convolution: gentle single_blinks (frontal_min -72 to -120µV) produce conv_min of -8 to -64 while strong talk artifacts produce conv_min of -100 to -1009. No threshold separates them.
- NCC: blinks NCC_min=-0.57 to -0.85, talk NCC_min=-0.68 to -0.90, rest NCC_min=-0.76 to -0.87. Complete overlap across all conditions.
- Streaming issue: on 4-sample chunks, the rolling buffer contains only a few blink samples when the template check runs. The convolution response is dominated by the surrounding noise in the buffer, making detection unreliable.

**Root cause:** The blink V-shape is too generic — many EEG artifacts (speech, baseline drift, electrode motion) produce similar frontal deflections with matching shape on 4 channels. Template matching requires spatial resolution (8+ channels) or temporal precision (buffer must contain complete blink waveform at time of check) that our streaming pipeline can't provide.

**Verdict: disabled.** `mf_threshold=0` (non-negative = disabled). The code remains in `_check_template()` for future use if better templates or more channels become available.

### Wide HF window — effective (v5)

The HF ratio guard (temporal/frontal HF energy) was unreliable on 4-sample chunks. Some clench chunks have momentarily low HF ratios (2.5-2.8) that slip through the 3.5 threshold.

**Fix:** Compute HF ratio over the last 128 samples (~500ms) from the rolling buffer instead of just the current 4-sample chunk. Added temporal rolling buffer alongside frontal buffer.

**Impact:**
- Clench FPs at -75µV: 20 (4-sample) → 12 (32-sample) → 3 (64-sample) → **1** (128-sample)
- Combined with speech detector: **F1=0.95** (P=0.95, R=0.95) with 0 rest FP, 1 clench FP, 1 talk FP

### Approaches tested but NOT implemented (ineffective on our data)

- **Kurtosis guard** (reject if < -0.5): kills too many double_blink trials (two peaks = low kurtosis). Would need per-event-type thresholds.
- **AF7-AF8 correlation** (reject if < 0.5): too noisy on 4-sample chunks, some real single_blinks have low bilateral correlation (-0.13 to 0.98 range).
- **Frontal/temporal amplitude ratio**: overlaps too much between conditions (blinks 0.22-1.0, talk 0.56-0.95).
- **Asymmetry ratio** (rise/fall time): noisy measurement on short windows, blink asymmetry (0.29-2.67) overlaps with everything.
- **Template matching / matched filter**: blink V-shape too generic, complete NCC overlap between blinks and talk artifacts (see above).

### Key insight: per-chunk features are noisy
Shape features work well on full trials but are noisy on 4-sample streaming chunks. The buffer-based approach (accumulate, then validate) is essential. Features that look great in papers (kurtosis, correlation, asymmetry) require hundreds of samples per measurement — not compatible with 4-sample-per-frame streaming without buffering. The HF ratio guard is a concrete example: 4-sample HF ratio is too noisy (clench FP=20), but 128-sample HF ratio works well (clench FP=1).

## Next Steps

- **ML classifier** — logistic regression or small NN on extracted features from all recorded data. Expected F1 > 0.98.
- **More training data** — record eyebrow_raise and eyebrow_furrow to expand the gesture vocabulary.

## Scripts

- `scripts/eval_blink_detector.py` — full evaluation harness (includes SpeechDetector)
- `scripts/compare_pipeline_vs_brainflow.py` — original pipeline comparison
