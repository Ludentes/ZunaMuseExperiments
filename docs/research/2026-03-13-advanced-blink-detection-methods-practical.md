# Research: Practical Advanced Blink Detection for Consumer EEG

**Date:** 2026-03-13
**Sources:** 12 sources (listed below)

---

## Executive Summary

Three methods stand out for improving our blink detector on 4-channel Muse data: **MAD-based robust thresholding** (drop-in replacement for mean/std, proven noise resilience), **wavelet coefficient analysis** (db4 at 4 levels, matches blink morphology), and **DTW template matching** (96.4% accuracy in literature, but computationally heavier). The BLINKER pipeline from VisLab combines MAD statistics with morphological validation (R² tent-shape fitting) and achieved robust results across 2000+ EEG datasets — this hybrid approach is the most promising architecture for our use case. A Muse-specific paper (MED) achieved 98.96% on single-channel Muse data using peak detection with sanity checks, confirming our hardware is sufficient.

**Recommendation:** Implement (1) MAD-based robust statistics as immediate upgrade to current detector, (2) BLINKER-style morphological validation (R² tent fitting) as a second method. These two are complementary, low-complexity, and proven on noisy consumer EEG.

---

## Key Findings

### 1. MAD-Based Robust Statistics

The Median Absolute Deviation replaces standard deviation in threshold calculations, providing outlier-resistant dispersion estimates. The formula is simple:

```
MAD = median(|x - median(x)|)
σ_robust = 1.4826 × MAD  (for normal distributions)
threshold = median + λ × σ_robust  (λ typically 6-9 for saccades, 2-5 for blinks)
```

The MAD saccade paper [1] demonstrated F1 improvements of 0.02-0.10 at noise levels ≥0.4, with the key advantage being that **MAD is immune to threshold drift caused by the very artifacts it's detecting**. Standard mean/std calculations get pulled by large blink deflections, raising the threshold and causing missed detections — exactly our baseline drift problem.

At low noise (<0.2), fixed thresholds are slightly better (F1 difference 0.003-0.004). At high noise (>0.3), MAD dramatically outperforms (F1 difference 0.24-0.76) [1]. This maps directly to our office demo problem: good-fit sessions (low noise) won't regress, poor-fit sessions (high noise) will improve substantially.

**Implementation cost:** Trivial. Replace `np.mean`/`np.std` with `np.median` and MAD calculation. No additional data structures needed. Computational overhead is negligible — median is O(n) and we're operating on 4-128 sample windows.

### 2. Wavelet Coefficient Analysis (db4, 4 levels)

The Daubechies-4 wavelet is the consensus choice for blink detection because its shape morphologically resembles the blink waveform [6]. At 256Hz sampling rate with 4-level decomposition:

- Level 1 detail (D1): 64-128 Hz (muscle noise, not useful)
- Level 2 detail (D2): 32-64 Hz (EMG artifacts)
- Level 3 detail (D3): 16-32 Hz (beta range)
- Level 4 detail (D4): 8-16 Hz (alpha range)
- Level 4 approximation (A4): 0-8 Hz (**blink energy lives here**)

Blinks are 0.1-3 Hz phenomena, so they concentrate in the approximation coefficients at level 4. The Stationary Wavelet Transform (SWT) variant avoids translation-invariance issues of standard DWT and is **12-27× faster** than ICA-based methods [6], processing 10 seconds of data in 1.8-2.8 seconds.

An automatic stopping criterion based on skewness analysis (threshold 0.15) was proposed to detect blink-contaminated levels without manual tuning [6]. A 2025 study using db1 at 3 levels with k-NN achieved 100% sensitivity and 95.23% specificity for blink detection [3].

**Implementation cost:** Moderate. PyWavelets (`pywt`) provides SWT. Main concern is latency — SWT needs a window of data (typically 128-256 samples = 0.5-1s), which we already buffer for our current detector. Real-time feasible but adds ~2ms per chunk.

**Practical concern for our case:** Wavelets excel at **separating** blinks from background EEG, but our problem isn't separation — it's detection in noisy, poorly-fitted data where the "background" itself is artifact. Wavelets won't help if the noise is in the same frequency band as blinks (which it often is with movement artifacts).

### 3. DTW Template Matching

DTW template matching achieved 96.42% accuracy on frontal channels (particularly Fz) when combined with k-means clustering and SVM [2]. The method scores EEG segments against multiple blink template categories, with clustering separating blink from non-blink score distributions.

A variant called Dynamic Positional Warping (DPW) outperformed standard DTW by warping on both ordinate and abscissa axes [7].

**Implementation cost:** High. DTW is O(n²) per comparison, and real-time detection requires comparing every sliding window against templates. Even with FastDTW (O(n·log(n))), at 256Hz with 128-sample windows this means ~64 DTW computations per second per channel. The clustering/SVM layer adds offline training requirements.

**Critical issue for our case:** We previously found that template matching doesn't work well on 4-channel Muse because the V-shape is too generic and NCC overlap is complete [memory]. DTW may improve on NCC by handling time distortion, but the fundamental problem remains — with only AF7/AF8, there's limited spatial discrimination.

### 4. BLINKER Pipeline (Recommended Architecture)

BLINKER [4] is the most mature system found, validated on 2000+ datasets across 8 labs. Its architecture combines multiple techniques we've been considering:

1. **Bandpass [1-20 Hz]** — removes DC drift and high-frequency noise
2. **Threshold detection**: Signal > 1.5 SD above mean → candidate (minimum 50ms duration, 50ms separation)
3. **Morphological validation**: Fit linear regression to inner 80% of upstroke and downstroke, compute R². Best blinks have R² ≥ 0.98, good blinks R² ≥ 0.90
4. **MAD-based outlier rejection**: Compute robust SD = 1.4826 × MAD. Reject blinks > 5 robust SD from median (best) or > 2 robust SD (good)
5. **Blink-Amplitude Ratio (BAR)**: mean amplitude within blink / mean amplitude in surrounding non-blink regions. Accept range [3, 50]
6. **Velocity discrimination**: pAVR ≤ 3 centiseconds → reject as saccade

Key extracted features per blink: half-zero duration, velocity-amplitude ratios (pAVR ~4cs alert, ~7cs drowsy), blink rate.

**Why this fits us:** BLINKER's architecture mirrors our existing guard-stack approach but replaces our ad-hoc guards with principled statistical measures. The R² tent-shape validation is a better version of our current shape guard. The MAD-based rejection is exactly the robust statistics upgrade we need. The BAR metric would help with our poor-fit sessions (low BAR = noise floor too close to blink amplitude).

**Implementation cost:** Moderate. Each component is simple. The R² calculation on upstroke/downstroke requires buffering the full blink waveform (which our trailing-edge detection already does). MAD is trivial. BAR needs a running estimate of non-blink amplitude.

### 5. MED: Muse-Specific Algorithm

The MED algorithm [5] was designed specifically for Muse hardware and achieved **98.96% accuracy on single-channel Muse data**. It uses deterministic peak detection with sanity checks:

1. Find local minima (initial blink location estimates)
2. Apply constraints: minimum distance between peaks, minimum voltage difference
3. Extract features from both phases of the eye-blink signal
4. Multiple sanity checks prevent false peaks and partial blinks

The key insight: MED works on a **single** Muse channel, meaning we have 4× the information available. Their accuracy ceiling suggests our hardware is not the bottleneck — our algorithm is.

## Comparison

| Method | Accuracy | Noise Robustness | Compute Cost | Implementation | Our Priority |
|--------|----------|------------------|--------------|----------------|-------------|
| MAD robust stats | +0.02-0.10 F1 at high noise | Excellent | Negligible | Drop-in | **#1 — immediate** |
| BLINKER R² + BAR | Validated 2000+ datasets | Good (multi-stage) | Low (~1ms) | Moderate (refactor guards) | **#2 — next** |
| Wavelet (db4 L4) | 95-100% sensitivity | Good for freq separation | Low (~2ms) | Moderate (pywt) | #3 — if needed |
| DTW templates | 96.4% | Moderate | High (O(n²)) | High (templates + SVM) | Skip — poor fit for 4ch |
| MED (Muse-specific) | 98.96% | Good (sanity checks) | Low | Low | Borrow sanity checks |

## Recommended Implementation Plan

**Phase 1: MAD upgrade (drop-in, ~1 hour)**
Replace `np.mean`/`np.std` baseline tracking with `np.median`/MAD. This directly fixes the threshold drift problem that caused 5/7 office demo sessions to fail. No architectural changes needed.

**Phase 2: BLINKER-style morphological validation (~half day)**
Replace our current shape guard with R² tent-shape fitting on upstroke/downstroke. Add BAR metric to reject blinks in high-noise sessions. Add pAVR velocity check to reject saccades. This replaces 3 of our current guards with more principled versions.

**Phase 3 (optional): Wavelet preprocessing**
If Phase 1+2 don't achieve sufficient accuracy on office demo data, add wavelet denoising (db4, 4-level SWT) as a preprocessing step before the detector. This would help separate blink energy from movement artifact energy.

## Open Questions

- How does BLINKER's R² approach handle the 4-sample streaming chunks we receive from BrainFlow? Need to buffer enough samples for a complete blink waveform before computing R².
- MED's sanity checks are not fully described in available abstracts — the full paper (IEEE SPMB 2022) would have implementation details.
- None of these methods address the fundamental fitting problem — a channel with no skin contact produces random noise regardless of algorithm sophistication. The fitting protocol must come first.

## Sources

[1] Makkeh, Thaler, & Engbert. "MAD saccade: statistically robust saccade threshold estimation via the median absolute deviation." J Vis. 2021. https://pmc.ncbi.nlm.nih.gov/articles/PMC7881893/
[2] Alirezaei & Sardouie. "Automatic EEG Blink Detection Using Dynamic Time Warping Score Clustering." Springer, 2018. https://link.springer.com/chapter/10.1007/978-3-030-02819-0_5
[3] Acharya et al. "EEG based real time classification of consecutive two eye blinks for BCI." Sci Rep, 2025. https://www.nature.com/articles/s41598-025-07205-0
[4] Kleifges, Bigdely-Shamlo, Kerick, & Robbins. "BLINKER: Automated Extraction of Ocular Indices from EEG." Front Neurosci, 2017. https://pmc.ncbi.nlm.nih.gov/articles/PMC5289990/
[5] Shovon et al. "MED: Muse-based Eye-blink Detection Algorithm Using a Single EEG Channel." IEEE SPMB, 2022. https://ieeexplore.ieee.org/document/10014708/
[6] Guarneros-Sandoval et al. "Low Complexity Automatic Stationary Wavelet Transform for Elimination of Eye Blinks from EEG." Sensors, 2020. https://pmc.ncbi.nlm.nih.gov/articles/PMC6955982/
[7] Chang et al. "Enhanced Template Matching Using Dynamic Positional Warping for Identification of Specific Patterns in EEG." J Appl Math, 2014. https://onlinelibrary.wiley.com/doi/10.1155/2014/528071
[8] Agarwal et al. "Blink: A Fully Automated Unsupervised Algorithm for Eye-Blink Detection." https://gnan.ece.gatech.edu/archive/agarwal-blink.pdf
[9] Singh et al. "A synergistic approach for enhanced eye blink detection using wavelet analysis, autoencoding and Crow-Search optimized k-NN." Sci Rep, 2025. https://www.nature.com/articles/s41598-025-95119-2
[10] Kleifges et al. BLINKER GitHub. https://github.com/VisLab/EEG-Blinks
[11] Minguillon et al. "A Hardware-Based Configurable Algorithm for Eye Blink Signal Detection Using a Single-Channel BCI Headset." Sensors, 2023. https://pmc.ncbi.nlm.nih.gov/articles/PMC10255990/
[12] Navarro-Meza et al. "Wavelet Design for Automatic Real-Time Eye Blink Detection and Recognition in EEG Signals." IJCCC, 2019. https://univagora.ro/jour/index.php/ijccc/article/view/3516
