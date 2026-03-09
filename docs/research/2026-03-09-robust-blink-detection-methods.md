# Robust Blink Detection Methods for Low-Channel EEG (Muse 2)

Date: 2026-03-09

## Problem Statement

Current blink detector uses:
1. Amplitude threshold (-75 uV on frontal AF7+AF8 average)
2. High-frequency energy ratio guard (temporal/frontal HF RMS ratio > 3.5 rejects clenches)

Performance: F1 = 0.90 on recorded data, but 8 false positives from speech trials. Speech produces large frontal deflections that mimic blink morphology in amplitude alone.

**Goal**: Distinguish blinks from jaw clenches AND speech artifacts on 4 channels (TP9, AF7, AF8, TP10) at 256 Hz, running in real-time (60 fps = ~16 ms budget per chunk).

## Key Artifact Characteristics

| Artifact | Frequency Band | Spatial Distribution | Duration | Waveform Shape |
|----------|---------------|---------------------|----------|----------------|
| **Blink** | 0.5-12 Hz (peak in delta/theta) | Maximal at frontal (AF7, AF8), attenuated at temporal | 200-400 ms | Asymmetric bell: fast downstroke (~92 ms), slow recovery (~242 ms), rounded peak |
| **Jaw clench** | 10-80 Hz (peak 40-80 Hz) | Maximal at temporal (TP9, TP10), spreads to frontal | 100-500 ms | High-frequency burst, irregular shape |
| **Speech** | Broadband but delta-dominant tongue glossokinetic potential | Broad frontal distribution, gradual gradient to posterior | Variable (100 ms - seconds) | Slower, more symmetric, often oscillatory, less peaked |

These differences are the foundation for all discrimination approaches below.

---

## 1. Template Matching / Cross-Correlation

### How it works
Build a canonical blink template (typically 300-400 ms window of the average blink waveform from calibration). For each detected candidate event, compute the normalized cross-correlation (NCC) between the candidate snippet and the template. Accept only if NCC exceeds a threshold (typically 0.85-0.95).

The normalized blink waveform is remarkably consistent across blinks within a subject and even across subjects ([Agarwal et al., "Blink: A Fully Automated Unsupervised Algorithm"](https://gnan.ece.gatech.edu/archive/agarwal-blink.pdf)). This means a generic template works, though a per-user calibration template is better.

### Why it helps with speech
Speech artifacts produce broader, more symmetric, often multi-peaked deflections. Their NCC against a sharp asymmetric blink template will be low. This directly addresses our false positive problem.

### Computational cost
NCC on a ~100-sample window (400 ms at 256 Hz) is trivial: one dot product + two norms. Well under 1 ms. Can be done with `numpy.correlate` or `scipy.signal.correlate`.

### Minimum channels
1 channel (frontal). We can average AF7+AF8 for better SNR.

### Published results
- Agarwal et al. "Blink" algorithm: 98.96% accuracy (OpenBCI), 99.2% (Muse) using template-based approach with low-pass filtering
- [BLINKER](https://vislab.github.io/EEG-Blinks/) uses 1.5 SD threshold + shape criteria (upstroke/downstroke R^2 > 0.90), widely validated

### Feasibility: HIGH
This is the single most impactful addition to our current detector. Low cost, directly addresses speech false positives, works on our channels. **Recommend implementing first.**

### Implementation sketch
```python
# Calibration: collect 10-20 blinks, extract 400ms windows centered on peak, average
template = np.mean(blink_snippets, axis=0)  # ~102 samples at 256 Hz
template = (template - template.mean()) / template.std()  # normalize

# Detection: for each candidate event
snippet = signal[peak_idx - 51 : peak_idx + 51]
snippet_norm = (snippet - snippet.mean()) / snippet.std()
ncc = np.dot(template, snippet_norm) / len(template)
if ncc > 0.85:
    accept_as_blink()
```

---

## 2. Wavelet-Based Detection

### How it works
Decompose the EEG signal using Discrete Wavelet Transform (DWT) or Stationary Wavelet Transform (SWT). Blinks concentrate energy in specific wavelet scales corresponding to 0.5-12 Hz. By examining wavelet coefficients at these scales, blinks can be isolated from higher-frequency EMG (clench) and broader-spectrum speech artifacts.

Common choices: Daubechies wavelets (db4, db8) with 4-5 level decomposition at 256 Hz:
- Level 4 detail (D4): 8-16 Hz
- Level 5 detail (D5): 4-8 Hz
- Level 5 approximation (A5): 0-4 Hz
Blinks appear primarily in D5 and A5.

### Why it helps with speech
Speech glossokinetic potentials have energy distributed differently across wavelet scales than blinks. Wavelet coefficients can be used as features to separate them. However, both blinks and speech are low-frequency, so wavelets alone may not be sufficient.

### Computational cost
DWT on 256 samples (1 second) with 5 levels: ~2500 multiply-add operations. Well under 1 ms. SWT is ~2x more expensive but still trivial.

BrainFlow provides `perform_wavelet_denoising()` which handles DWT internally.

### Minimum channels
1 channel.

### Published results
- VME-DWT: detects 95% of blinks with SNR -8 to +3 dB ([PubMed](https://pubmed.ncbi.nlm.nih.gov/33497337/))
- SWT-based method: 18% improvement over DWT for artifact separation ([PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC6955982/))
- Wavelet + SVM: 98.4% accuracy, 99.1% sensitivity, 97.2% specificity

### Feasibility: MEDIUM
Useful as a feature extraction stage (feed wavelet coefficients into a classifier), but not a standalone discriminator between blinks and speech. Best combined with template matching or ML.

---

## 3. ICA / Miniature Source Separation

### How it works
Independent Component Analysis decomposes N channels into N independent sources. With enough channels, one component typically captures eye blinks, which can be identified and separated from brain signals.

### Why it does NOT help us
ICA requires many more channels than sources to separate. With 4 channels, ICA produces only 4 components. The blink source, brain sources, and noise sources all get mixed into these 4 components with poor separation quality.

Rule of thumb from the literature: **minimum ~20 channels for reliable ICA artifact separation** ([EEGLAB documentation](https://eeglab.org/tutorials/06_RejectArtifacts/RunICA.html), [SCCN UCSD](https://sccn.ucsd.edu/~jung/Site/EEG_artifact_removal.html)).

### Computational cost
FastICA on 4x256 matrix: ~1-5 ms. Not the bottleneck.

### Minimum channels
20+ for reliable separation. 4 is far too few.

### Feasibility: NOT FEASIBLE
With only 4 channels, ICA cannot reliably separate blink from brain + speech + EMG sources. **Do not pursue.**

---

## 4. Matched Filtering

### How it works
A matched filter is the theoretically optimal detector for a known signal shape in additive white Gaussian noise. Design an FIR filter whose impulse response is the time-reversed blink template. Convolve the EEG with this filter; the output peaks when the input best matches the blink shape.

This is mathematically equivalent to cross-correlation with the template (approach #1), but implemented as a causal filter that can run continuously on the streaming data rather than on extracted snippets.

### Why it helps with speech
Same reasoning as template matching: speech waveforms produce lower filter output because they don't match the blink impulse response shape.

### Computational cost
FIR filter with ~100 taps at 256 Hz: 100 multiply-adds per sample = ~25,600 ops/sec per channel. Negligible. Can be implemented with `scipy.signal.lfilter` or `numpy.convolve`.

### Minimum channels
1 channel.

### Published results
Matched filters are standard in radar/communications signal detection. In EEG, this is essentially what template matching does but in filter form. No separate F1 numbers beyond template matching literature.

### Feasibility: HIGH
Practically equivalent to template matching but with the advantage of running as a continuous streaming filter rather than requiring event extraction first. **Good alternative implementation of approach #1.**

### Implementation sketch
```python
# Design matched filter (time-reversed, energy-normalized template)
matched_filt = template[::-1] / np.sum(template**2)

# Apply continuously to streaming frontal average
filtered = np.convolve(frontal_avg, matched_filt, mode='same')

# Detect peaks in filtered output
peaks = detect_peaks(filtered, threshold=adaptive_thresh)
```

---

## 5. Peak Shape Features

### How it works
Extract morphological features from each candidate event and use them to discriminate blinks from other artifacts:

| Feature | Blink Typical | Clench | Speech |
|---------|--------------|--------|--------|
| **Rise time** (10-90% amplitude) | ~50-100 ms | <30 ms (sharp EMG onset) | >100 ms (gradual) |
| **Fall time** (90-10% amplitude) | ~150-250 ms | <50 ms | >100 ms |
| **Asymmetry ratio** (rise/fall) | 0.3-0.5 (fast rise, slow fall) | ~1.0 (symmetric) | ~0.7-1.0 (more symmetric) |
| **Duration** (above half-max) | 150-300 ms | <150 ms | >300 ms often |
| **Kurtosis** of window | High (sharp peak) | Medium | Low (broad) |
| **Skewness** | Negative (asymmetric) | ~0 | Variable |
| **Zero-crossing rate** | Low (smooth curve) | High (high-freq oscillation) | Medium |

### Why it helps with speech
Speech artifacts are typically broader, more symmetric, and lower kurtosis than blinks. The asymmetry ratio alone may reject most speech false positives since blinks have a distinctive fast-rise/slow-fall pattern that speech does not.

### Computational cost
All features are computed on a ~100-sample window: a few dozen numpy operations. Well under 0.1 ms.

### Minimum channels
1 channel.

### Published results
- [Tandfonline 2025](https://www.tandfonline.com/doi/full/10.1080/08839514.2025.2587985): blink features (including shape metrics) used as predictors with deep learning
- BLINKER uses upstroke/downstroke R^2 > 0.90 as shape quality criterion
- Multi-dimensional feature fusion achieved high specificity ([ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S1746809423000903))

### Feasibility: HIGH
Extremely cheap to compute, easy to add as guard conditions on top of current threshold detector. **Recommend implementing alongside template matching.**

### Key features to implement first
1. **Asymmetry ratio** (rise_time / fall_time): reject if > 0.7 (blinks are always asymmetric)
2. **Duration**: reject if > 400 ms or < 100 ms
3. **Kurtosis** of the 400 ms window: reject if < 3.0 (speech is flatter)

---

## 6. Machine Learning on Waveform Snippets

### How it works
Extract a fixed-length window (e.g., 400 ms = 102 samples at 256 Hz) around each candidate event from 1-4 channels. Feed raw samples or extracted features into a lightweight classifier.

**Classifier options (in order of simplicity):**
1. **Logistic regression** on features (rise time, fall time, asymmetry, kurtosis, NCC, frontal/temporal ratio): ~10 features, <0.01 ms inference
2. **Random Forest** (10-50 trees) on same features: <0.1 ms inference
3. **Small 1D CNN** (3 conv layers, ~1K parameters) on raw 4x102 matrix: <1 ms inference with numpy, <0.1 ms with ONNX
4. **SVM with RBF kernel** on features: <0.01 ms inference

### Published results
- Logistic regression: 97.91% accuracy on eye state classification ([ScienceDirect](https://www.sciencedirect.com/science/article/pii/S240584402101361X))
- RT-Blink (Random Forest, 60 ms window): 96.54% sensitivity, 91.25% precision, 5.07 ms average processing time ([IEEE Xplore](https://ieeexplore.ieee.org/document/10006405/))
- XGBoost/SVM/NN ensemble: 89% accuracy for multi-blink classification ([Nature](https://www.nature.com/articles/s41598-025-07205-0))
- Wavelet + autoencoder + optimized k-NN: enhanced detection ([Nature](https://www.nature.com/articles/s41598-025-95119-2))

### Computational cost
Feature-based classifiers: <0.1 ms per event. Even a tiny neural net is <1 ms. Far within our 16 ms budget.

### Minimum channels
1 channel for basic detection; 4 channels improve discrimination between blink/clench/speech.

### Feasibility: HIGH (but requires training data)
We already have recorded trial data (blink, clench, talk protocols). Training a logistic regression or random forest on extracted features is straightforward. **Recommend as phase 2 after features + template matching are working.**

### Training data plan
From our existing recordings:
- `single_blink/`, `double_blink/`, `triple_blink/` trials: positive examples
- `clench/` trials: negative examples (clench class)
- `talk/` trials: negative examples (speech class)
- `rest/` trials: negative examples (no-event class)

Extract candidate events from all recordings, label by trial type, train classifier.

---

## 7. Adaptive Thresholding

### How it works
Instead of a fixed -75 uV threshold, use a running z-score:

```
z = (value - running_mean) / running_std
```

Detect blinks when z > threshold (typically 3-5 SD). The running baseline adapts to:
- Electrode drift
- Per-session amplitude differences
- Impedance changes over time

BLINKER uses 1.5 SD above mean as its adaptive threshold ([BLINKER docs](https://vislab.github.io/EEG-Blinks/)).

### Why it helps
- Eliminates need for per-user calibration of fixed uV threshold
- Handles electrode impedance changes during session
- Running baseline excludes previous blinks from corrupting the mean

### Why it does NOT help with speech specifically
Speech artifacts can also exceed 3-5 SD. Adaptive thresholding alone does not discriminate event shape -- it only improves the initial candidate detection stage. Must be combined with shape/template features.

### Computational cost
Running mean and std with exponential moving average: 2 multiplies + 2 adds per sample. Essentially free.

### Implementation
```python
class AdaptiveThreshold:
    def __init__(self, alpha=0.001, threshold_sd=4.0):
        self.mean = 0.0
        self.var = 1.0
        self.alpha = alpha  # EMA decay (slow, excludes transients)
        self.threshold_sd = threshold_sd

    def update(self, sample):
        # Only update baseline during non-event periods
        self.mean = (1 - self.alpha) * self.mean + self.alpha * sample
        self.var = (1 - self.alpha) * self.var + self.alpha * (sample - self.mean)**2

    def is_candidate(self, sample):
        sd = max(np.sqrt(self.var), 1.0)  # floor to avoid div/0
        return abs(sample - self.mean) / sd > self.threshold_sd
```

### Feasibility: HIGH
Should replace our fixed -75 uV threshold regardless of other improvements. **Recommend implementing immediately.**

---

## 8. Multi-Channel Spatial Patterns

### How it works
Exploit the known topography differences between artifact types on the Muse 2 channel layout:

```
        AF7 ---- AF8       (frontal, near eyes)
       /              \
    TP9              TP10   (temporal, near jaw/ears)
```

**Blink spatial signature:**
- Large amplitude at AF7, AF8 (near eyes)
- Attenuated at TP9, TP10 (far from eyes)
- AF7 and AF8 are highly correlated (both eyes blink together)
- Frontal/temporal amplitude ratio: typically > 3:1

**Jaw clench spatial signature:**
- Large amplitude at TP9, TP10 (near temporalis/masseter)
- Moderate at AF7, AF8
- High-frequency content (40-80 Hz) dominates
- Temporal/frontal amplitude ratio: > 2:1 in HF band

**Speech spatial signature:**
- Moderate amplitude at all channels (glossokinetic potential is broadly distributed)
- Frontal/temporal ratio: ~1:1 to 2:1 (more uniform than blinks)
- AF7-AF8 correlation may be lower (tongue movements are less bilaterally symmetric than blinks)

### Discriminative features
1. **Frontal/temporal amplitude ratio** (already partially implemented): `mean(|AF7|, |AF8|) / mean(|TP9|, |TP10|)`
   - Blink: > 3.0
   - Speech: 1.0 - 2.5
   - Clench: < 1.0 (in HF band)

2. **AF7-AF8 correlation** (within the event window):
   - Blink: > 0.9 (bilateral blink)
   - Speech: 0.3 - 0.8 (less symmetric)
   - Clench: variable

3. **Temporal HF energy ratio** (our existing guard, can be refined):
   - Compute RMS in 30-80 Hz band for temporal vs frontal
   - Clench: temporal HF >> frontal HF
   - Blink: temporal HF ~ frontal HF (both low)

### Computational cost
3-4 ratio computations on ~100-sample windows: negligible (<0.1 ms).

### Minimum channels
2 minimum (1 frontal + 1 temporal). 4 channels (our setup) is ideal for this approach.

### Feasibility: HIGH
We already use the temporal/frontal HF ratio. Adding frontal/temporal amplitude ratio and AF7-AF8 correlation should significantly help with speech discrimination. **Recommend implementing alongside other features.**

---

## Recommended Implementation Plan

### Phase 1: Quick wins (estimated 2-4 hours)
These changes should push F1 from 0.90 to ~0.95+:

1. **Replace fixed threshold with adaptive z-score** (approach #7)
   - EMA baseline with slow alpha (0.001), threshold at 4.0 SD
   - Freeze baseline updates during detected events

2. **Add peak shape guards** (approach #5)
   - Asymmetry ratio: reject if rise_time/fall_time > 0.7
   - Duration guard: reject if event duration > 400 ms or < 100 ms
   - Kurtosis guard: reject if window kurtosis < 3.0

3. **Add frontal/temporal amplitude ratio** (approach #8)
   - Reject if frontal_amp / temporal_amp < 2.5 (speech is more spatially uniform)

4. **Add AF7-AF8 correlation guard** (approach #8)
   - Reject if correlation < 0.8 (blinks are bilateral)

### Phase 2: Template matching (estimated 4-6 hours)
Should push F1 to ~0.97+:

5. **Build per-user blink template** from calibration
   - Collect 10-20 confirmed blinks during calibration protocol
   - Average and normalize to create template
   - Use NCC > 0.85 as acceptance criterion

6. **Implement as matched filter** (approach #4) for continuous streaming
   - Apply to frontal channel average (AF7+AF8)/2
   - Peak detection on filter output

### Phase 3: ML classifier (estimated 1-2 days)
Should push F1 to ~0.98+:

7. **Extract features from recorded data** using approaches #5 and #8
8. **Train logistic regression** on labeled blink/clench/speech/rest snippets
9. **Export as simple coefficient array** for real-time inference
10. **A/B test** against rule-based detector

### What NOT to implement
- **ICA** (approach #3): not feasible with 4 channels
- **Deep learning** (large CNN/transformer): overkill for this problem, logistic regression on good features will match or exceed
- **Complex wavelet decomposition** as standalone: use wavelets only as feature extraction if needed for ML

---

## BrainFlow Built-in Functions to Leverage

From the [BrainFlow signal processing API](../2026-03-08-brainflow-signal-processing-api.md):

- `DataFilter.detect_peaks_z_score(data, lag, threshold, influence)` -- adaptive z-score peak detection, can replace our manual threshold logic
- `DataFilter.perform_wavelet_denoising(data, wavelet, level)` -- pre-clean signal before feature extraction
- `DataFilter.get_custom_band_powers(data, bands, channels, sr, apply_filters)` -- compute specific band powers for HF ratio

---

## References

- [Agarwal et al., "Blink: A Fully Automated Unsupervised Algorithm for Eye-Blink Detection in EEG"](https://gnan.ece.gatech.edu/archive/agarwal-blink.pdf) -- template-based, 98.96% accuracy on OpenBCI, 99.2% on Muse
- [BLINKER: Automated blink detector for EEG](https://vislab.github.io/EEG-Blinks/) -- 1.5 SD adaptive threshold + shape criteria
- [RT-Blink: Real-Time Blink Detection from Single Frontal EEG](https://ieeexplore.ieee.org/document/10006405/) -- Random Forest, 60 ms window, 96.54% sensitivity, 5.07 ms processing
- [VME-DWT: Detection and Elimination of Eye Blink From Short Segments](https://pubmed.ncbi.nlm.nih.gov/33497337/) -- wavelet-based, 95% detection
- [Low Complexity Automatic Stationary Wavelet Transform](https://pmc.ncbi.nlm.nih.gov/articles/PMC6955982/) -- SWT 18% better than DWT
- [EEG signal analysis: Logistic regression, ANN, SVM, CNN](https://pmc.ncbi.nlm.nih.gov/articles/PMC8203713/) -- logistic regression 97.91%
- [Multi-dimensional EEG feature fusion](https://www.sciencedirect.com/science/article/abs/pii/S1746809423000903) -- feature fusion for blink detection
- [EEG Artifacts: Types, Detection, and Removal](https://www.bitbrain.com/blog/eeg-artifacts) -- EMG vs EOG frequency characteristics
- [Physiological artifacts in scalp EEG](https://pmc.ncbi.nlm.nih.gov/articles/PMC5553928/) -- jaw clench EMG peak at 40-80 Hz
- [Real-time classification of consecutive eye blinks for BCI](https://www.nature.com/articles/s41598-025-07205-0) -- XGBoost/SVM/NN 89% multi-blink
- [Wavelet + autoencoder + optimized k-NN for blink detection](https://www.nature.com/articles/s41598-025-95119-2) -- synergistic approach
- [Re-purposing EEG Artifacts: Blink Features as Drowsiness Predictors](https://www.tandfonline.com/doi/full/10.1080/08839514.2025.2587985) -- blink shape features
- [Unsupervised Eye Blink Artifact Detection with GMM](https://pubmed.ncbi.nlm.nih.gov/33560994/) -- channel correlation + fractal dimension
- [EEGLAB ICA tutorial](https://eeglab.org/tutorials/06_RejectArtifacts/RunICA.html) -- ICA channel requirements
- [EOG blink waveform characteristics](https://pmc.ncbi.nlm.nih.gov/articles/PMC11133197/) -- 334 ms duration, 92 ms downstroke, 242 ms upstroke
