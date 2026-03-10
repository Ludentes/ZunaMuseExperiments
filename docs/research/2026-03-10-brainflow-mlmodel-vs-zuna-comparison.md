# BrainFlow MLModel vs ZUNA: State Classification Comparison

**Date:** 2026-03-10
**Data:** 3×30s eyes-closed + 3×30s eyes-open recordings
**Script:** inline analysis (to be formalized)

## Objective

Compare brain state discrimination (eyes-open vs eyes-closed) across three approaches:
1. BrainFlow MLModel on raw 4 Muse channels (baseline)
2. BrainFlow MLModel on ZUNA-reconstructed channels
3. Custom alpha/beta ratio on ZUNA virtual channel groups

## Results

### BrainFlow MLModel (Mindfulness/Restfulness scores, 0-1 scale)

| Input | EC mindful | EO mindful | Separation | Notes |
|-------|-----------|-----------|------------|-------|
| Raw 4ch | 0.227 ± 0.103 | 0.475 ± 0.151 | 0.248 | Baseline |
| ZUNA 4ch (denoised) | 0.193 ± 0.130 | 0.498 ± 0.147 | **0.306** | +23% from denoising alone |
| ZUNA all 23ch | 0.193 ± 0.128 | 0.495 ± 0.151 | 0.301 | Extra channels don't help MLModel |

### Custom Alpha/Beta Ratio by Channel Group

| Channel group | EC ratio | EO ratio | Separation |
|--------------|----------|----------|------------|
| Orig 4ch (TP9+AF7+AF8+TP10) | 1.19 ± 0.48 | 0.87 ± 0.23 | 0.32 |
| Occipital (O1+O2) | 1.31 ± 0.67 | 0.83 ± 0.27 | **0.48** |
| Central (C3+Cz+C4) | 1.31 ± 0.62 | 0.91 ± 0.34 | 0.40 |
| Parietal (P3+Pz+P4) | 1.23 ± 0.62 | 0.88 ± 0.29 | 0.35 |
| All 23ch averaged | 1.25 ± 0.54 | 0.87 ± 0.21 | 0.38 |

## Key Findings

### 1. ZUNA denoising improves BrainFlow MLModel (+23%)
Even on the same 4 channels, ZUNA's diffusion model cleans the signal enough to improve mindfulness separation from 0.248 → 0.306. The model doesn't add channels here — it just produces a cleaner version of the original 4.

### 2. More channels don't help BrainFlow's MLModel
Feeding 23ch vs 4ch to `get_avg_band_powers` → `MLModel.predict` gives nearly identical results (0.301 vs 0.306). The MLModel averages band powers across channels, so adding more channels just dilutes the discriminative ones.

### 3. Virtual occipital channels give best custom feature separation
Alpha/beta ratio at ZUNA's virtual O1+O2 gives 0.48 separation — 50% better than the original 4ch (0.32). These channels are physically absent on Muse 2.

### 4. High variance undermines all approaches
EC alpha/beta std is 0.48-0.67, meaning the distributions overlap heavily. Even the best separation (0.48 at occipital) has overlapping ranges:
- EC: 0.64–1.98 (mean ± 1 std)
- EO: 0.56–1.10
- Overlap zone: 0.56–1.10 (significant)

## Viability Assessment

| Separation | Binary accuracy (est.) | Continuous control | Demo quality |
|-----------|----------------------|-------------------|-------------|
| 0.25 | ~65-70% | Very noisy | Poor |
| 0.30 | ~70-75% | Noisy, needs heavy smoothing | Marginal |
| 0.48 | ~75-80% | Usable with 10-15s smoothing | Marginal-OK |
| 0.80+ | ~90%+ | Responsive, 2-3s latency | Good |

Current best (0.48 at occipital) needs significant temporal smoothing to feel reliable, adding latency that hurts the "wow" factor.

## Conclusion

ZUNA provides measurable improvement for spectral brain state features, especially through virtual occipital channels. However, the absolute discrimination level (0.3–0.5 separation with high variance) is marginal for a compelling real-time demo. The signal is real but noisy — would need either:
- Heavy temporal smoothing (10-15s window → sluggish response)
- Per-session calibration with adaptive thresholds
- More discriminative task contrasts (e.g., meditation vs mental math, not just eyes open/closed)
- Combination of multiple feature channels for a richer classifier
