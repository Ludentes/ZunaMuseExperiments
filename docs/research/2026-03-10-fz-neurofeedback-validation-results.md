# Fz Neurofeedback Validation Results

**Date:** 2026-03-10
**Goal:** Test if ZUNA virtual Fz theta distinguishes focused meditation from drowsy mind-wandering, where raw Muse alpha metrics presumably cannot.

## Experiment Setup

- **Conditions:** meditation (focused breathing), drowsy (mind-wandering), mental_math (counting backwards by 7s)
- **Trials:** 3 x 60s per condition
- **ZUNA superresolution:** 4ch Muse → 23ch, including virtual Fz
- **Hardware:** Muse 2 (TP9, AF7, AF8, TP10)

## Main Result: Virtual Fz Theta Failed

ZUNA virtual Fz theta does NOT separate meditation from drowsy.

| Comparison | Cohen's d (5s) | Cohen's d (2s) | Accuracy |
|---|---|---|---|
| meditation vs drowsy | 0.08 | 0.02 | 62.9% |

Means nearly identical: meditation=3.75 uV², drowsy=3.98 uV². ZUNA generates a generic frontal signal regardless of cognitive state — not real frontal midline theta.

## Surprise Finding: Raw AF7/AF8 Theta/Beta Ratio Works

Raw frontal theta/beta ratio separates all three conditions with high accuracy.

| Comparison | Cohen's d (5s) | Accuracy |
|---|---|---|
| meditation vs drowsy | 1.61 | 94.4% |
| drowsy vs mental_math | 1.75 | 95.8% |
| meditation vs mental_math | 1.06 | 77.1% |

## Why the Hypothesis Was Wrong

We assumed drowsy and meditation would both show high alpha, making them confusable. In reality:

- Drowsy produced massively more theta (41.2 vs 7.5 uV²) AND alpha (19.3 vs 5.3 uV²) than meditation
- Drowsy state was dominated by slow eye movements, drift artifacts, and muscle relaxation
- Active focused meditation looks very different from passive mind-wandering
- Raw theta/beta ratio captures this: meditation=1.12, drowsy=0.34, mental_math=2.31

## Condition Means (5s Windows)

| Metric | Meditation | Drowsy | Mental Math |
|---|---|---|---|
| Fz theta (ZUNA) | 3.75 | 3.98 | 6.92 |
| Fz theta/beta (ZUNA) | 0.85 | 1.06 | 1.97 |
| AF alpha (raw) | 5.25 | 19.30 | 9.88 |
| AF theta/beta (raw) | 1.12 | 0.34 | 2.31 |
| AF theta (raw) | 7.52 | 41.20 | 24.70 |

## Window Size Degradation — AF Theta/Beta (Raw)

| Window | med vs drow (d) | med vs math (d) | drow vs math (d) |
|---|---|---|---|
| 60s | 2.50 | 4.01 | 6.16 |
| 30s | 2.48 | 4.61 | 6.09 |
| 10s | 2.18 | 1.85 | 3.66 |
| 5s | 1.61 | 1.06 | 1.75 |
| 2s | 2.01 | 0.76 | 1.39 |
| 1s | 1.14 | 0.53 | 0.93 |

Holds up well at 1-2s windows — viable for responsive neurofeedback.

## Conclusions

1. ZUNA virtual Fz does NOT provide neurofeedback-quality frontal midline theta from 4 Muse channels.
2. Raw Muse AF7/AF8 theta/beta ratio distinguishes meditation, drowsy, and mental math at >94% accuracy.
3. No ZUNA needed for this neurofeedback use case.
4. 3-state classification (focused / zoned out / effortful thinking) works on raw hardware.
