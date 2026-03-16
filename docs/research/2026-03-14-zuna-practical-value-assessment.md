# ZUNA Practical Value Assessment — 2026-03-14

Comprehensive evaluation of ZUNA v0.1.1 (380M-param masked diffusion autoencoder, 4ch -> 23ch superresolution) against all recorded BCI data (28 labels, ~61MB). Answers: does ZUNA help our detectors? Does it enable new capabilities? What can we actually measure with Muse 2?

## TL;DR

**ZUNA does NOT help existing detectors. Raw 4ch is better for blinks, clenches, and speech detection.** ZUNA's one clear win is stabilizing frontal alpha asymmetry (FAA) — epoch-to-epoch CV drops from 2.17 to 0.35 for rest condition. Everything else is either unchanged or worse.

For the thinking board questions: **Focus, Fatigue, and Relaxation are all measurable on raw 4ch Muse.** ZUNA adds latency (30-90s/recording) without meaningful improvement.

---

## 1. Existing Detectors

### Blink Detector — NO BENEFIT

| Metric | Raw | ZUNA | Verdict |
|--------|-----|------|---------|
| AF7 deflection (single_blink) | 972.7 uV | 703.5 uV | -28% |
| AF8 deflection (single_blink) | 970.7 uV | 632.3 uV | -35% |
| AF7 SNR | 40.7 | 32.0 | Worse |
| AF8 SNR | 60.2 | 42.7 | Worse |
| AF7-AF8 bilateral corr | 0.184 | 0.178 | Same |

ZUNA *reduces* blink amplitude by 28-35%. Blink propagation to virtual channels (Fp1/Fp2 at SNR 21-30) is interesting scientifically but useless for detection — we already detect blinks at SNR 40+ on raw.

### Clench Detector — HURTS

| Channel | Raw HF power | ZUNA HF power | Raw HF/LF ratio | ZUNA HF/LF ratio |
|---------|-------------|---------------|-----------------|------------------|
| TP9 (clench) | 9.0 | 7.3 | 0.12 | 0.10 |
| TP10 (clench) | 16.7 | 10.7 | 0.26 | 0.18 |
| TP9 (rest) | 2.9 | 0.5 | 0.22 | 0.02 |

ZUNA smooths high-frequency EMG content. The clench-vs-rest HF ratio on TP10 drops from 0.26/0.03=8.7x to 0.18/0.01=18x — the ratio happens to look better because ZUNA suppresses rest HF more than clench HF. But absolute HF power is lower, which means less headroom for detection in noisy conditions.

Virtual temporal channels (T3/T4/T5/T6) have even less HF content (0.3-5.7). No value.

### Speech Guard — NO BENEFIT

Talk condition: ZUNA collapses temporal LF power from 304 to 12 uV^2. The raw signal contains the EMG information; ZUNA strips it. Our adaptive speech guard relies on HF temporal energy, which ZUNA reduces.

---

## 2. New Capabilities

### SSVEP (Visual BCI) — NOT VIABLE

Tested all stimulus frequencies (3-15 Hz). Key finding: **the no-stimulus baseline has the same SNR as stimulated conditions** at 6Hz (6.5 dB baseline vs 6.6 dB stimulus) and 7Hz (6.1 dB baseline vs 3.9 dB stimulus). This means we're not detecting a visual evoked response — just alpha-band noise.

Only low-frequency flicker (3-4 Hz) shows genuine above-baseline SNR (13.1 dB at 3Hz vs 6.5 dB baseline), but this is motion/MEP artifact, not usable for BCI.

ZUNA doesn't help: occipital channels show same SNR patterns as frontal muse channels.

**Conclusion: SSVEP is not viable on Muse 2 with frontal+temporal electrodes, regardless of ZUNA.**

### Drowsiness — RAW IS BETTER, ZUNA DISTORTS

Raw 4ch shows drowsy has 2.3x more theta than rest — a genuine, expected finding (drowsiness increases theta power).

ZUNA **reverses this**: drowsy shows *less* theta than rest in all virtual channel groups (ratio 0.31-0.57). This is physically implausible and indicates ZUNA is distorting spectral content in the virtual channels.

| Region | Theta drowsy/rest ratio (ZUNA) | Expected |
|--------|-------------------------------|----------|
| frontal_muse | 0.50 | >1.0 |
| occipital | 0.35 | >1.0 |
| parietal | 0.31 | >1.0 |

**Conclusion: Use raw 4ch for drowsiness detection. ZUNA is actively harmful here.**

### Focus/Concentration (theta/beta ratio) — NO IMPROVEMENT

| Condition | Raw frontal theta/beta | ZUNA frontal theta/beta | Raw CV | ZUNA CV |
|-----------|----------------------|------------------------|--------|---------|
| Meditation | 4.82 | 4.80 | 0.47 | 0.46 |
| Mental math | 18.24 | 18.30 | 0.74 | 0.75 |

ZUNA perfectly preserves theta/beta on muse frontal channels (as expected — same physical channels). Virtual channels show inflated ratios (central=24.66, parietal=27.85 for mental_math) — unrealistically high, suggesting spectral hallucination.

ZUNA central theta/beta has slightly lower CV (0.39 vs 0.47 for meditation) but this is on 2 epochs for rest, so not reliable.

**Conclusion: Theta/beta ratio works on raw 4ch. ZUNA adds nothing.**

### Alpha Asymmetry — ONE CLEAR WIN

| Condition | Raw FAA mean | Raw FAA CV | ZUNA FAA mean | ZUNA FAA CV |
|-----------|-------------|-----------|--------------|------------|
| Meditation | -0.531 | 0.67 | -0.532 | 0.64 |
| Rest | -0.218 | 2.17 | -0.393 | **0.35** |
| Eyes closed | -0.076 | 6.11 | -0.059 | 7.24 |
| Mental math | -0.090 | 10.14 | -0.061 | 14.72 |

For rest condition, ZUNA dramatically reduces FAA epoch-to-epoch variability (CV from 2.17 to 0.35). The FAA signal becomes much more stable and potentially usable for emotional valence tracking.

However, F4-F3 asymmetry (classic 10-20 FAA) shows opposite sign from AF8-AF7 — suggesting virtual channel alpha may not reflect real lateral differences.

**Conclusion: ZUNA stabilizes AF8-AF7 FAA in some conditions. Marginal benefit, and F4-F3 is unreliable.**

### Spatial Coherence — SUSPICIOUS

| Condition | Alpha coherence | Beta coherence | Theta coherence |
|-----------|----------------|---------------|----------------|
| Meditation | 0.022 | 0.011 | 0.018 |
| Rest | 0.154 | 0.139 | 0.208 |
| Eyes closed | 0.337 | 0.197 | 0.457 |
| Mental math | 0.519 | 0.570 | 0.379 |

Inter-channel coherence varies 25x between conditions (meditation=0.02, mental_math=0.52). Real EEG doesn't vary this much. ZUNA appears to reconstruct spatially differentiated patterns, but these likely reflect learned statistical associations rather than real neural source separation.

---

## 3. What Can We Actually Measure? (Thinking Board Q)

This answers the thinking board question: "We throw around focus, relaxation, fatigue but what do the formulas actually compute?"

### Focus / Concentration

- **EEG signature**: Theta (4-8Hz) / Beta (13-30Hz) ratio. Lower = more focused.
- **Formula**: `theta_power / beta_power` on frontal channels (AF7, AF8)
- **Channels**: Muse frontal (AF7, AF8). ZUNA virtual channels NOT helpful.
- **Validated on Muse?**: YES — meditation vs mental_math shows d=1.24 (STRONG effect, p<0.0001)
- **Our accuracy**: Reliable for state discrimination (meditation vs thinking). Less reliable for continuous scoring due to CV=0.47-0.74.
- **BrainFlow MINDFULNESS model**: Uses proprietary features. Our theta/beta ratio is comparable.

### Relaxation

- **EEG signature**: Alpha (8-13Hz) power increase, especially on temporal channels
- **Formula**: `alpha_power` or `alpha_power / beta_power` on temporal channels
- **Channels**: Muse temporal (TP9, TP10) best for alpha. Frontal usable but weaker.
- **Validated on Muse?**: YES — eyes_closed vs eyes_open shows d=0.43 temporal (p=0.07), approaching significance
- **Our accuracy**: Moderate. Alpha blocking works for binary eyes-open/closed. Continuous "relaxation score" needs smoothing (rolling 10-30s window).

### Fatigue / "Brain Fry"

- **EEG signature**: Theta INCREASE over time, alpha DECREASE over time, theta/alpha ratio increase
- **Formula**: `theta_trend_over_time` or `theta_alpha_ratio` comparing time windows
- **Channels**: Frontal (AF7, AF8) for theta, temporal for alpha
- **Validated on Muse?**: PARTIALLY — drowsy shows 2.3x theta vs rest (raw 4ch). But our "drowsy" recording was only ~30s. Need 30+ minute recordings to validate trending.
- **Our accuracy**: Unknown. Need proper fatigue protocol (long work session with periodic subjective ratings).
- **Key insight**: Fatigue is NOT an instantaneous metric. It's a TREND. Need moving window comparison: `theta_now / theta_baseline_30min_ago`.

### Emotional Valence (via Alpha Asymmetry)

- **EEG signature**: Frontal alpha asymmetry (FAA) — more left-frontal alpha = positive affect
- **Formula**: `log(alpha_AF8) - log(alpha_AF7)` (or F4-F3 on full 10-20)
- **Channels**: AF7, AF8 (Muse frontal)
- **Validated on Muse?**: WEAK — meditation FAA is stable (CV=0.67) but rest/mental_math FAA is noisy (CV=2-10)
- **Our accuracy**: Only reliable during sustained calm states. Not reliable during active cognition.

### Drowsiness / Microsleep

- **EEG signature**: Theta increase + alpha decrease + slow eye movements
- **Formula**: `theta / alpha` or `theta_power` frontal, combined with eye movement detection
- **Channels**: Frontal (AF7, AF8) for theta/alpha, frontal for slow eye movements
- **Validated on Muse?**: YES for theta increase (2.3x in drowsy), but need longer recordings
- **Key insight**: Combine theta/alpha ratio with blink rate (drowsy = slow, long blinks). Our BlinkDetector can track blink rate already.

---

## 4. Practical Recommendations

### Drop ZUNA for real-time BCI
ZUNA adds 30-90s processing latency and doesn't improve any existing or planned detector. All our detectors work on raw 4ch.

### Keep ZUNA data for research
The 23ch reconstructions are stored at `recordings/<label>/zuna_output_raw.fif`. They may have value for:
- Academic comparison / publishing
- Future ZUNA versions (v0.2+)
- Understanding what the model learned vs what's real

### Focus on raw 4ch metrics
The practical measurement stack on Muse 2:
1. **Focus**: theta/beta frontal ratio (STRONG discrimination, d=1.24)
2. **Relaxation**: alpha power temporal (MEDIUM discrimination, d=0.43)
3. **Fatigue**: theta trend over time (needs validation protocol)
4. **Blinks**: frontal deflection (99% accuracy on good fit)
5. **Clenches**: temporal HF EMG (95% accuracy)
6. **Drowsiness**: theta + slow blink combination (needs validation)

### Next steps for the Brain Fry detector
1. Record 30-60 minute focus session with subjective fatigue reports every 5 min
2. Compute rolling theta/beta ratio in 30s windows
3. Correlate trend with subjective reports
4. If correlation > 0.5: build real-time fatigue trending detector
5. All on raw 4ch. No ZUNA needed.

---

## Raw Data Locations

- Concatenated raw 4ch: `recordings/<label>/zuna_concat_raw.fif`
- ZUNA 23ch output: `recordings/<label>/zuna_output_raw.fif`
- Evaluation results: `experiments/zuna_comprehensive_eval.json`, `experiments/zuna_detector_eval.json`
