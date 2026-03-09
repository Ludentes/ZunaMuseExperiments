# BrainFlow DataFilter API Catalog for BCI (Muse 2, 256Hz)

**Date:** 2026-03-08
**Purpose:** Catalog BrainFlow's signal processing API to decide what to reuse vs build custom

---

## Filtering (all work in-place on numpy arrays)

| Function | Signature | What it does | Use? |
|---|---|---|---|
| `perform_bandpass` | `(data, sr, start_freq, stop_freq, order, filter_type, ripple)` | Standard bandpass. FilterTypes: BUTTERWORTH(0), CHEBYSHEV_TYPE_1(1), BESSEL(2), plus zero-phase variants (3,4,5). | **YES** — core preprocessing. Butterworth zero-phase 1-50Hz. |
| `perform_bandstop` | `(data, sr, start_freq, stop_freq, order, filter_type, ripple)` | Notch/band-reject. | **YES** — 50/60Hz powerline removal. |
| `perform_highpass` | `(data, sr, cutoff, order, filter_type, ripple)` | Highpass filter. | **YES** — remove DC drift, 0.5-1Hz. |
| `perform_lowpass` | `(data, sr, cutoff, order, filter_type, ripple)` | Lowpass filter. | **MAYBE** — 45Hz lowpass as bandpass alternative. |
| `perform_rolling_filter` | `(data, period, operation)` | Moving average (MEAN=0) or median (MEDIAN=1). | **YES** — smooth band power time series. |
| `remove_environmental_noise` | `(data, sr, noise_type)` | Convenience notch. NoiseTypes: FIFTY(0), SIXTY(1), FIFTY_AND_SIXTY(2). | **YES** — simplest powerline removal. |

## Feature Extraction / Spectral Analysis

| Function | Signature | What it does | Use? |
|---|---|---|---|
| `get_psd_welch` | `(data, nfft, overlap, sr, window) -> (amps, freqs)` | Welch PSD estimate. | **YES** — already using. Core of band power computation. |
| `get_band_power` | `(psd, freq_start, freq_end) -> float` | Integrates PSD over frequency range. | **YES** — already using after get_psd_welch. |
| `get_avg_band_powers` | `(data_2d, channels, sr, apply_filter) -> (avg, stddev)` | Average + stddev of band powers across channels. Fixed bands: delta(1-4), theta(4-8), alpha(8-13), beta(13-30), gamma(30-50). | **YES** — convenience function, could replace our manual per-channel loop. |
| `get_custom_band_powers` | `(data_2d, bands, channels, sr, apply_filter) -> (avg, stddev)` | Same but user-defined frequency bands as list of tuples. | **YES** — define `[(4,8), (13,30)]` to directly get theta+beta for ratio. Cleaner than manual PSD. |

## Peak / Event Detection

| Function | Signature | What it does | Use? |
|---|---|---|---|
| `detect_peaks_z_score` | `(data, lag=5, threshold=3.5, influence=0.1) -> array` | Z-score peak detection. Returns array of -1/0/1. Lag = smoothing window, threshold = stddev threshold, influence = how much peaks affect running mean. | **YES** — key function for blink detection (frontal channels) and jaw clench detection (high-freq EMG band). |

## Denoising

| Function | Signature | What it does | Use? |
|---|---|---|---|
| `perform_wavelet_denoising` | `(data, wavelet, decomp_level, denoising_type, threshold, extension, noise_level)` | Wavelet denoising. In-place. Wavelets: db4, sym4, coif, bior, etc. | **YES** — good complement to bandpass. db4 at level 4-5 for 256Hz EEG. |
| `perform_wavelet_transform` | `(data, wavelet, decomp_level, extension) -> (coeffs, lengths)` | Forward wavelet transform. | **MAYBE** — wavelet features at specific levels = frequency bands. |
| `restore_data_from_wavelet_detailed_coeffs` | `(data, wavelet, decomp_level, level_to_restore) -> data` | Extract signal from single wavelet detail level. | **MAYBE** — at 256Hz with db4: L1=64-128Hz, L2=32-64Hz, L3=16-32Hz(beta), L4=8-16Hz(alpha), L5=4-8Hz(theta). |

## Spatial Filtering / Source Separation

| Function | Signature | What it does | Use? |
|---|---|---|---|
| `perform_ica` | `(data_2d, num_components, channels) -> (W, K, A, S)` | ICA. Returns unmixing W, whitening K, mixing A, sources S. | **MAYBE** — limited with 4 channels but could separate blink artifacts from neural signals. |
| `get_csp` | `(data_3d, labels) -> (filters, eigenvalues)` | Common Spatial Patterns. Binary classification. | **MAYBE** — for concentration vs relaxation with calibration data. |

## Signal Quality

| Function | Signature | What it does | Use? |
|---|---|---|---|
| `get_railed_percentage` | `(data, gain) -> float` | Percentage of samples at ADC limits. | **YES** — direct quality indicator. |
| `calc_stddev` | `(data) -> float` | Standard deviation. | **YES** — low = flatline, high = excessive noise. |

## Built-in ML Classifiers (brainflow.ml_model.MLModel)

| Metric | Description | Use? |
|---|---|---|
| `MINDFULNESS` (0) | Concentration/focus scoring. | **YES** — try before building custom theta/beta classifier. |
| `RESTFULNESS` (1) | Relaxation scoring. | **YES** — try before building custom. |
| `USER_DEFINED` (2) | Load custom ONNX model. | **MAYBE** — train custom blink/clench classifier. |

Usage:
```python
from brainflow.ml_model import MLModel, BrainFlowModelParams, BrainFlowMetrics, BrainFlowClassifiers

params = BrainFlowModelParams(BrainFlowMetrics.MINDFULNESS.value, BrainFlowClassifiers.DEFAULT_CLASSIFIER.value)
model = MLModel(params)
model.prepare()
# input is output of get_avg_band_powers
prediction = model.predict(feature_vector)
model.release()
```

---

## Decision: Reuse vs Build

### Reuse from BrainFlow (no custom implementation needed)

- **Filtering pipeline**: `remove_environmental_noise` + `perform_bandpass`
- **Band power extraction**: `get_custom_band_powers` or `get_psd_welch` + `get_band_power`
- **Theta/beta ratio**: `get_custom_band_powers` with `[(4,8), (13,30)]`, divide
- **Concentration/relaxation scoring**: `MLModel(MINDFULNESS/RESTFULNESS)` — try built-in before custom
- **Peak detection**: `detect_peaks_z_score` on filtered channel data
- **Wavelet denoising**: `perform_wavelet_denoising` as preprocessing step
- **Signal quality**: `get_railed_percentage` + `calc_stddev`
- **Detrending**: `detrend` before spectral analysis

### Must build ourselves

- **Blink detection logic**: `detect_peaks_z_score` on AF7/AF8 + bandpass 1-10Hz + peak polarity/duration validation + refractory period (prevent double-counting) + single/double/triple pattern matching
- **Jaw clench detection logic**: Bandpass >20Hz on TP9/TP10 → compute envelope → `detect_peaks_z_score` or threshold → duration/debounce logic
- **Alpha blocking detection**: Compare alpha power against personal baseline (calibration step). BrainFlow gives band powers, state-change detection is ours
- **Artifact rejection pipeline**: BrainFlow has ICA but automated component rejection (which component is artifact) must be custom. Simpler amplitude-threshold rejection is easy
- **Real-time windowing/buffering**: Sliding window manager, epoch extraction, overlap handling
- **Calibration/baseline management**: Personal baseline computation, adaptive thresholds
- **State machine / event logic**: Debouncing, refractory periods, event classification, state transitions
- **MQTT bridge**: Detected events → paho-mqtt → Home Assistant

### Quick wins to try first

1. `MLModel(MINDFULNESS)` / `MLModel(RESTFULNESS)` — built-in classifiers, no training needed
2. `detect_peaks_z_score` — single function for blink + clench detection
3. `get_custom_band_powers` — simpler than our manual PSD loop
4. `perform_wavelet_denoising` — potentially better signal quality than bandpass alone
