# Fz Neurofeedback Validation: Does ZUNA Virtual Fz Enable Frontal Midline Theta?

## Objective

Validate whether ZUNA's virtual Fz channel provides a neurofeedback-quality frontal midline theta (FMth) signal that distinguishes focused attention from drowsiness — something raw Muse AF7/AF8 alpha metrics cannot do. Current data shows Fz theta/beta d=3.34 on 60s averages (meditation vs math), but the critical test is whether Fz theta can separate focused meditation from drowsy mind-wandering, where alpha-based metrics fail because both states show high alpha.

## The Discrimination Problem

| Condition | Expected alpha (AF7/AF8) | Expected FMth (Fz) |
|---|---|---|
| Focused meditation | High | High |
| Drowsy/mind-wandering | High | **Low** |
| Mental math (already recorded) | Low | High |

Alpha cannot distinguish row 1 from row 2. If Fz theta can, ZUNA enables a neurofeedback modality impossible on raw Muse.

## New Recording: "drowsy" Condition

### Protocol

- 3 x 60s trials, 10s rest between
- Eyes closed, no focus target

### Subject Instructions

1. Put on the headband, get comfortable, close your eyes.
2. When you hear the cue beep, **do nothing intentional**. Don't count breaths, don't focus on anything.
3. Let your mind wander freely. Think about random things. Get bored. Zone out.
4. If you catch yourself focusing, stop focusing. The goal is the opposite of meditation.
5. Stay still (no jaw clenches, no talking). Just be unfocused.

### RecordingPanel Entry

Add to the protocols array in `frontend/src/components/RecordingPanel.tsx`:

```ts
{ label: "drowsy", trialDuration: 60, cueAt: 0, reps: 3, restBetween: 10, instruction: "Eyes closed, let your mind wander — don't try to focus" },
```

Place it after `mental_math` and before the SSVEP block.

## Analysis Script: `scripts/eval_fz_validation.py`

```
PYTHONPATH=. python scripts/eval_fz_validation.py
```

Expects recordings in: `recordings/{meditation,mental_math,drowsy}/<session>/*_raw.fif`

### Part A: Window Size Degradation Curve

For each window size in [60, 30, 10, 5, 2, 1] seconds:
1. Slice each condition's concatenated data into non-overlapping windows
2. Per window, compute:
   - FMth: theta (4-8 Hz) power at virtual Fz (from ZUNA output)
   - AF alpha: alpha (8-13 Hz) power averaged over AF7+AF8 (from original 4ch)
3. Compute Cohen's d between each condition pair:
   - meditation vs drowsy (the KEY comparison)
   - meditation vs math
   - drowsy vs math

Output: table of d values by window size and condition pair, for both FMth and AF alpha.

### Part B: 3-Condition Discrimination Matrix

For each metric, compute Cohen's d for all three condition pairs:

| Metric | med vs drowsy | med vs math | drowsy vs math |
|---|---|---|---|
| Fz theta (4-8 Hz) | ? | ? | ? |
| AF7+AF8 alpha (8-13 Hz) | ? | ? | ? |
| Fz theta/beta ratio | ? | ? | ? |
| BrainFlow mindfulness | ? | ? | ? |

Use 5s windows as the default timescale. The KEY cell is **med vs drowsy** for Fz theta — it must show separation where AF alpha does not.

### Part C: Binary Classification Accuracy

For each feature x window size combination:
1. Pool windows from both conditions
2. Find optimal threshold (brute-force over percentiles of combined distribution)
3. Report accuracy, sensitivity, specificity

Focus reporting on 2s and 5s windows (neurofeedback-relevant timescales).

### Implementation Notes

- Reuse `run_zuna()`, `find_fif_files()`, `concat_fifs()`, `band_power()` from `scripts/eval_zuna_alpha.py`
- ZUNA inference runs once per condition on full concatenated data, then windows are sliced from the output
- Cohen's d: `(mean1 - mean2) / pooled_std` — use `scipy.stats` or compute manually
- BrainFlow mindfulness: `MLModel(BrainFlowModelParams(BrainFlowMetrics.MINDFULNESS, BrainFlowClassifiers.DEFAULT_CLASSIFIER))` — feed it 5s chunks of the original 4ch data

## Success Criteria

| Level | med vs drowsy Fz theta (5s) | med vs drowsy AF alpha (5s) |
|---|---|---|
| **Minimum** | d > 0.5 | d < 0.3 |
| **Good** | d > 0.8 | d < 0.3 |
| **Excellent** | d > 0.8 on **2s** windows | d < 0.3 |

The critical point: Fz theta must separate what AF alpha cannot. If AF alpha also separates them (d > 0.5), the test is inconclusive — we need conditions where alpha genuinely fails.

## What This Proves If Successful

1. ZUNA's virtual Fz carries real frontal midline theta information, not just a copy of AF7/AF8.
2. This enables **meditation quality feedback** that distinguishes genuine focused attention from zoning out — impossible with raw Muse alpha alone.
3. Practical application: real-time neurofeedback loop where the feedback signal is ZUNA Fz theta, updated every 2-5s.
4. Justifies the ZUNA inference cost (~10s per 60s segment on GPU) for applications where alpha is insufficient.
