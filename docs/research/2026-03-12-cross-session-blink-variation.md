# Cross-Session Blink Amplitude Variation on Muse 2

**Date:** 2026-03-12
**Data:** 3 recording sessions across different dates (Mar 9, Mar 12, Mar 13)
**Hardware:** Muse 2 EEG headband, 4 channels (TP9, AF7, AF8, TP10) at 256Hz

---

## Executive Summary

Blink amplitude on the Muse 2 frontal channels (AF7, AF8) varies by 10-20x across sessions due to headband positioning. The BlinkDetector v5 (F1=0.95 on Mar 9 data) degrades severely on quieter sessions where blinks are only 2-3 standard deviations from baseline. No fixed or adaptive threshold reliably detects blinks across all sessions. A calibration phase or multi-feature approach is needed.

## The Problem

BlinkDetector v5 was developed and tuned on Mar 9 recordings where blinks produced large, clean deflections (-305 to -1000 uV on frontal channels). When tested on later sessions, detection collapsed.

## Session Comparison (AF7+AF8 Frontal Channels)

| Session | Blink Amplitude Range (uV) | Signal SD (uV) | Blink/SD Ratio | Detection at sd=3.0 |
|---------|---------------------------|----------------|----------------|---------------------|
| Mar 9   | -1000 to -305             | 29.2           | ~10-34x        | Excellent (F1=0.95) |
| Mar 12  | -92 to -49                | 7.9            | ~6-12x         | Moderate            |
| Mar 13  | -90 to -42                | 5.5            | ~7.5-16x       | Poor (1/20 at sd=3) |

The Mar 9 session had blinks 10-34x the baseline SD. Mar 13 had blinks only 7.5-16x — and with lower absolute SD, the absolute amplitude of blinks dropped into ranges that overlap with normal EEG variation.

## Root Cause: Headband Positioning

The frontal electrodes (AF7, AF8) sit differently relative to the orbicularis oculi muscle depending on headband position. Even small shifts change the signal-to-noise ratio dramatically:

- **Tight/low fit** (Mar 9): Electrodes closer to the eye muscles, blinks produce large deflections, higher baseline SD from muscle proximity
- **Loose/high fit** (Mar 12, 13): Electrodes further from eye muscles, blinks are attenuated, lower baseline SD

This is a fundamental limitation of consumer-grade dry-electrode EEG. Medical-grade systems with fixed electrode caps and conductive gel have far less session-to-session variation.

## Detection Analysis

### Fixed threshold (`threshold_uv=-50`)

Acts as a hard gate. On Mar 9 (loud session), every blink exceeds -50 uV easily. On Mar 13 (quiet session), some blinks are only -42 uV and get blocked entirely. A fixed threshold tuned for one session is meaningless for another.

### Adaptive threshold (SD-based)

Changed to adaptive-only threshold once baseline is established (fixed threshold only for cold start). Results on Mar 13 data:

| SD Multiplier | Blinks Detected (of 20) | Rest False Positives (of 20) |
|---------------|------------------------|------------------------------|
| 3.0           | 1                      | 5                            |
| 2.0           | 6                      | 10                           |

The fundamental issue: with baseline SD=5.5 uV, blinks at -42 uV are only ~2.5 SDs below baseline. At sd=2.0, you catch more blinks but also catch normal EEG fluctuations. At sd=3.0, you miss almost everything. There is no SD multiplier that separates blinks from noise in this session.

### Why adaptive threshold alone is insufficient

When blinks are only 2-3 SDs from baseline, they live inside the normal distribution of EEG amplitude variation. The distributions overlap. No threshold on a single feature (amplitude) can separate them cleanly. Additional features are needed.

## Implications

1. **No single threshold works across sessions.** What works for Mar 9 (loud signal) fails for Mar 13 (quiet signal). This applies to both fixed and adaptive thresholds.

2. **Adaptive threshold helps but is not sufficient.** When blinks are only 2-3 SDs from baseline, they overlap with normal EEG variation. The adaptive approach moves the threshold appropriately but cannot overcome the fundamental SNR limitation.

3. **Calibration phase is needed.** A short "blink 5 times" calibration at session start could establish per-session blink amplitude and set a session-specific threshold with known sensitivity.

4. **Shape-based detection may help.** Blinks have a characteristic V-shape waveform (sharp negative deflection + recovery in 100-200ms) that could distinguish them from noise even at low amplitude. Previous template matching via NCC failed on 4ch Muse (see detector lessons doc), but time-domain shape features (rise time, symmetry, duration) might work without correlation.

5. **Multi-feature approach is the likely solution.** Combining amplitude with duration, bilateral correlation (AF7-AF8), and frequency content could improve robustness in low-SNR sessions where amplitude alone is ambiguous.

## Potential Solutions (Not Yet Implemented)

### 1. Session Calibration
Ask user to blink N times at session start. Measure actual blink amplitudes for this session. Set threshold as a fraction of observed blink amplitude rather than baseline SD.

**Pros:** Simple, directly measures what we need.
**Cons:** Requires user cooperation, adds friction to session start.

### 2. Running Blink Model
Track detected blink amplitudes during session. Dynamically adjust threshold based on observed blink distribution. Start with conservative threshold, relax as blink statistics are learned.

**Pros:** No explicit calibration step, adapts continuously.
**Cons:** Cold start problem — may miss early blinks before model is trained. Chicken-and-egg: need to detect blinks to learn blink amplitudes.

### 3. BrainFlow's `detect_peaks_z_score`
Built-in peak detection that uses a rolling window z-score approach. May handle variation better than our manual threshold because it adapts to local signal statistics continuously.

**Pros:** Already implemented in BrainFlow, well-tested.
**Cons:** Still fundamentally amplitude-based, may have same SNR limitation.

### 4. Bilateral Correlation
Real blinks are highly correlated between AF7 and AF8 because the orbicularis oculi contracts bilaterally. Random noise and single-channel artifacts are not correlated. Use AF7-AF8 correlation within a short window as an additional feature.

**Pros:** Orthogonal to amplitude, adds genuine discriminative power.
**Cons:** Requires synchronized buffering across channels, adds complexity. May fail if one electrode has poor contact.

### 5. Wavelet-Based Detection
Decompose the signal using wavelets, look for blink-shaped components at the characteristic blink frequency (1-5 Hz, 100-200ms duration) regardless of absolute amplitude. This separates the shape from the scale.

**Pros:** Amplitude-invariant, directly captures blink morphology.
**Cons:** More computationally expensive, requires tuning wavelet parameters. BrainFlow has `perform_wavelet_denoising` but not wavelet-based event detection.

## Recommended Next Step

**Session calibration (Solution 1)** is the lowest-risk, highest-impact improvement. It directly addresses the core problem (unknown per-session amplitude) with minimal complexity. Implement a 10-second "blink 5 times" prompt at session start, measure the median blink amplitude, and set the detection threshold at 50% of that amplitude.

If calibration alone is insufficient, add **bilateral correlation (Solution 4)** as an additional guard layer — it follows the proven multi-layer architecture of BlinkDetector v5 and provides genuinely orthogonal information.

---

## References

- `docs/research/2026-03-09-muse2-detector-lessons.md` — detector development lessons, multi-layer architecture
- `docs/research/2026-03-09-blink-detection-evaluation.md` — BlinkDetector v5 evaluation on Mar 9 data
- `docs/research/2026-03-08-muse2-data-validation.md` — validated Muse 2 data ranges
