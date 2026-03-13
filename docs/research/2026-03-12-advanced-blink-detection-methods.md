# Research: Advanced Blink Detection Methods for Consumer EEG

**Date:** 2026-03-12
**Sources:** 14 sources (see below)

---

## Executive Summary

Naive amplitude thresholding fails on consumer-grade 4-channel EEG (Muse 2) because blink amplitude varies 10-20x across sessions due to headband positioning. The most promising amplitude-invariant approaches are: (1) **Dynamic Time Warping (DTW)** template matching, which normalizes amplitude and compares waveform shape (96% accuracy); (2) **Wavelet decomposition** (VME-DWT) to isolate blink-shaped components regardless of scale (95% detection at SNR -8 to +3 dB); (3) **The BLINK unsupervised algorithm** which self-learns per-user blink profiles from natural blink frequency (F1=0.96, single-channel); and (4) **Lightweight CNN/RNN** on raw or feature windows (93-96% single-channel). ICA is not viable with 4 channels. Kalman filters address baseline tracking but not the core amplitude-invariance problem.

## Key Findings

### 1. Dynamic Time Warping (DTW) — Most Directly Applicable

DTW aligns two time series by warping the time axis, making it inherently amplitude-invariant when combined with normalization. A DTW score clustering approach achieved 96.42% average accuracy for blink detection in continuous EEG during cognitive workload assessment, using 7 channels without EOG [1]. The method works by computing DTW distance between each EEG window and a blink template — low distance = blink match. Unlike our previous NCC template matching (which failed because the V-shape is too generic), DTW handles duration variation and can be amplitude-normalized before comparison.

The key insight from DTW research is that "the variability across user-specific eye-blink waveforms is so high across users when considering amplitude deviation that what looks like an eye-blink waveform for one user is simply noisy perturbations for another" [1]. This directly describes our cross-session problem. DTW addresses it by comparing shape, not scale.

**Feasibility for our system:** DTW on a 256-sample window (1s) takes ~1ms in Python with scipy/tslearn. Compatible with 4-sample streaming if we buffer 128-256 samples. Can use BrainFlow's existing wavelet denoising as preprocessing. Single-channel (AF7 or AF8) is sufficient.

### 2. Wavelet Decomposition (VME-DWT) — Best for Low-SNR

The VME-DWT algorithm uses Variational Mode Extraction to locate blink intervals, then Discrete Wavelet Transform to filter only contaminated intervals [2]. It detects 95% of eye blinks from contaminated EEG signals with SNR ranging from -8 to +3 dB — directly relevant to our low-SNR sessions where blinks are only 2-3 SDs from baseline. The method operates on single-channel data and is "computationally-efficient, filtering contaminated EEG signals in millisecond time resolution" [2].

A separate approach uses a custom-designed wavelet matched to the blink waveform shape for detection and localization, achieving real-time detection with a sliding window [3]. The wavelet coefficients at blink-relevant scales (1-5 Hz, corresponding to 100-200ms blink duration) spike regardless of absolute amplitude.

BrainFlow already provides `perform_wavelet_denoising` with various wavelet types. We could use DWT decomposition at level 4-5 to extract the 1-4 Hz component where blinks live, then apply threshold on the wavelet coefficient magnitude rather than raw amplitude. This is amplitude-normalized by construction.

**Feasibility:** BrainFlow has `DataFilter.perform_wavelet_denoising` and `DataFilter.perform_wavelet_transform`. Needs 128+ samples per window (already our buffer size). Python pywt library is an alternative with more control.

### 3. BLINK Algorithm — Unsupervised Self-Learning

The BLINK algorithm by Agarwal & Sivakumar (2019) is fully unsupervised — it self-learns user-specific blink profiles from natural blink frequency without any training labels [4]. It achieved F1=0.96 on reading tasks and F1=0.94 on video watching tasks across 12 subjects. Key properties:

- Works on single-channel EEG
- Requires only that the user blinks naturally (3+ blinks in the signal)
- Self-discovers blink morphology per user
- Code available at github.com/meagmohit/BLINK (Python)

The algorithm processes a window of EEG, finds local minima with constraints on minimum distance and voltage difference, then clusters them to distinguish blinks from noise. It leverages the fact that blinks are the most stereotyped artifact in EEG — even when amplitude varies, the relative shape is consistent within a session.

**Feasibility:** Python implementation exists. Requires a few seconds of data with natural blinks to bootstrap. Could run as a calibration step or continuously adapt. Main concern: designed for batch processing of recording segments, may need adaptation for streaming.

### 4. BLINKER — Robust Statistics Approach

The BLINKER toolbox uses robust standard deviation (1.4826 × MAD) instead of regular SD for threshold computation [5]. "Best" blinks must have amplitudes within 5 robust SDs of the best median, while "good" blinks need 2 robust SDs. It computes ~30 features per blink including duration, amplitude-velocity ratios, closing/reopening times.

The MAD-based approach is more resistant to outliers than our current EMA-based baseline, which can be pulled by large artifacts. However, BLINKER is MATLAB-based and designed for offline analysis.

**Key takeaway:** Replace our EMA baseline variance with MAD-based robust statistics. This is a simple change that directly improves threshold stability.

### 5. Machine Learning Approaches

**CNN on raw EEG windows:** A 10-layer CNN achieved 99.67% accuracy for blink artifact detection [6]. A CNN-RNN hybrid (BiLSTM) achieved 93.8% on single-channel, 95.4% on 3 channels [7]. These models take raw EEG windows (typically 0.5-1s) as input and output blink/no-blink classification.

**Classical ML with features:** XGBoost/SVM/NN on extracted features (SD, kurtosis, peak-to-peak, band powers) achieved 89% for classifying no-blink/single/double [8]. The most discriminative features were delta/theta band power and peak-to-peak amplitude.

**YOLOv8 on EEG images:** Converting time-series to images and applying object detection achieved 99.5% mAP@50 for blink localization [8]. Creative but heavy for real-time embedded use.

**Feasibility:** We have ~200 labeled trials. A small CNN (3-5 layers) on 256-sample windows is feasible to train and run in real-time (<1ms inference). Could use PyTorch (already installed for ZUNA). Main risk: may not generalize across sessions without session-specific fine-tuning.

### 6. ICA — Not Viable with 4 Channels

ICA requires at least as many channels as independent sources to separate. With 4 channels, we'd get 4 components — not enough to cleanly separate brain activity, blink artifact, EMG, and other noise [9]. ICA is designed for 16+ channel systems. Single-channel alternatives like SSA (Singular Spectrum Analysis) + k-means have been proposed [10] but are computationally expensive and designed for artifact removal, not detection.

### 7. Kalman Filter — Useful for Baseline, Not Detection

Kalman filters have been used for EEG baseline drift compensation and EOG artifact modeling [11]. They're excellent for tracking a slowly-varying baseline (our EMA approach, but better), but don't directly solve blink detection. A Kalman filter could replace our `_update_baseline` EMA with a proper state-space model that tracks baseline mean, variance, and drift rate — making the adaptive threshold more stable. However, this doesn't address the fundamental amplitude-invariance problem.

## Comparison

| Method | Accuracy | Channels | Real-time | Amplitude-Invariant | Complexity | Our Data |
|--------|----------|----------|-----------|---------------------|------------|----------|
| DTW template | 96% | 1 | Yes (1ms) | Yes (normalized) | Low | Untested |
| VME-DWT | 95% | 1 | Yes (ms) | Yes (wavelet scale) | Medium | Untested |
| BLINK unsup. | F1=0.96 | 1 | Batch→adapt | Yes (self-learning) | Medium | Untested |
| BLINKER MAD | ~95% | 1+ | Yes | Partial (robust SD) | Low | Easy port |
| CNN small | 94-99% | 1-3 | Yes (<1ms) | Yes (learned) | High (train) | 200 trials |
| ICA | N/A | 16+ min | No | N/A | High | **Not viable** |
| Kalman baseline | N/A | 1 | Yes | No | Low | Complement |
| Current (ours) | 80% | 2 | Yes | No | Low | Baseline |

## Recommended Path Forward

**Phase 1 (Quick wins, 1-2 hours):**
1. **Replace EMA baseline with MAD-based robust statistics** — direct improvement to current detector, no new dependencies
2. **Add wavelet coefficient thresholding** — use BrainFlow's DWT at level 5 on AF7, threshold the detail coefficients at 1-4 Hz scale. This is amplitude-normalized by construction.

**Phase 2 (Medium effort, half day):**
3. **Implement DTW template matching** — buffer 256 samples, z-normalize, compute DTW distance to a session-average blink template. DTW handles amplitude and duration variation. scipy has `dtw` or use tslearn.
4. **Port BLINK algorithm concepts** — use the self-learning approach: after detecting N blinks with wavelet/DTW, build a session-specific profile and tighten thresholds.

**Phase 3 (If needed, 1-2 days):**
5. **Train a small CNN** — 3-layer 1D CNN on 256-sample windows from our 200 trials. Use z-normalization per window to handle amplitude variation. Fine-tune per session with the first few detected blinks.

## Open Questions

- How does VME perform on 4-sample streaming chunks vs batch? May need to buffer 128+ samples.
- Can DTW run fast enough on every chunk, or should it be triggered only after a preliminary amplitude-based candidate detection?
- The BLINK algorithm's Python code quality is unknown — may need significant adaptation for streaming.
- None of the papers tested on Muse 2 specifically with dry electrodes and the extreme amplitude variation we see (10-20x).

## Sources

[1] Dynamic Time Warping Score Clustering for EEG Blink Detection. https://link.springer.com/chapter/10.1007/978-3-030-02819-0_5
[2] Shahbakhti et al. "VME-DWT: An Efficient Algorithm for Detection and Elimination of Eye Blink From Short Segments of Single EEG Channel." IEEE TNSRE, 2021. https://ieeexplore.ieee.org/document/9335960/
[3] Wavelet Design for Automatic Real-Time Eye Blink Detection. https://www.researchgate.net/publication/333560833
[4] Agarwal & Sivakumar. "Blink: A Fully Automated Unsupervised Algorithm for Eye-Blink Detection in EEG Signals." IEEE Allerton, 2019. https://github.com/meagmohit/BLINK
[5] BLINKER: Automated Blink Detector. https://vislab.github.io/EEG-Blinks/
[6] CNN for Eye Blink Artifact Detection. https://arxiv.org/pdf/2107.14235
[7] Detecting Blinks with Deep Learning. https://arxiv.org/html/2509.04951v1
[8] EEG real-time classification of consecutive eye blinks. https://pmc.ncbi.nlm.nih.gov/articles/PMC12217743/
[9] ICA for EEG artifact removal — minimum channel requirements. https://www.researchgate.net/post/What-is-the-minimum-number-of-EEG-channels-that-required-to-properly-run-ICA
[10] Eye-blink artifact removal from single channel EEG with k-means and SSA. https://www.nature.com/articles/s41598-021-90437-7
[11] Kalman filter for EEG eye blink artifact removal. https://ieeexplore.ieee.org/document/6513162
[12] MED: Muse-based Eye-blink Detection Algorithm. https://ieeexplore.ieee.org/document/10014708/
[13] BLINKER robust standard deviation approach. https://vislab.github.io/EEG-Blinks/
[14] Synergistic wavelet + autoencoder + k-NN for blink detection. https://www.nature.com/articles/s41598-025-95119-2
