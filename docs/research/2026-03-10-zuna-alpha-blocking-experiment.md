# ZUNA Superresolution Evaluation: Alpha Blocking Experiment

**Date:** 2026-03-10
**ZUNA version:** 0.1.1
**GPU:** RTX 5090 (32GB VRAM, ~3.7GB used)
**Script:** `scripts/eval_zuna_alpha.py`

## Objective

Determine whether ZUNA's superresolution (4 → 23 channels) produces spatially meaningful virtual channels from Muse 2 data, or just hallucinated noise.

## Experiment Design

**Alpha blocking** is the gold standard EEG sanity check: closing eyes increases alpha (8-13Hz) power, especially at occipital electrodes (O1, O2). Muse 2 has no occipital channels — if ZUNA's virtual O1/O2 show alpha blocking, the spatial reconstruction is meaningful.

### Protocol
- **Eyes open:** 3 × 30s trials (stare at screen, keep still)
- **Eyes closed:** 3 × 30s trials (close eyes, relax, keep still)
- Trials concatenated per condition → 90s each → 17-18 ZUNA epochs (5s each)

### ZUNA Pipeline
- Preprocessing: notch filter, 0.5Hz highpass, no average reference (only 4ch)
- Channel upsampling: 4 → 23 (standard 10-20 montage via spherical spline interpolation)
- Inference: 50 diffusion steps, GPU 0, data_norm=10.0

## Results

### Original 4 Channels

| Region | EC alpha (µV²) | EO alpha (µV²) | EC/EO | Verdict |
|--------|---------------|----------------|-------|---------|
| Frontal (AF7+AF8) | 12.7 | 11.0 | 1.15x | WEAK |
| Temporal (TP9+TP10) | 58.8 | 16.0 | 3.68x | GOOD |

Temporal channels pick up alpha blocking well (likely volume-conducted from parieto-occipital cortex). Frontal channels show minimal difference.

### ZUNA Reconstructed 23 Channels

| Region | EC alpha (µV²) | EO alpha (µV²) | EC/EO | Verdict |
|--------|---------------|----------------|-------|---------|
| Frontal orig (AF7+AF8) | 11.9 | 7.3 | 1.64x | GOOD |
| Temporal orig (TP9+TP10) | 29.5 | 15.0 | 1.97x | GOOD |
| **Occipital (O1+O2)** | **7.1** | **2.8** | **2.54x** | **GOOD** |
| Parietal (P3+Pz+P4) | 6.9 | 3.1 | 2.22x | GOOD |
| Central (C3+Cz+C4) | 6.8 | 2.3 | 2.90x | GOOD |
| Frontal virtual (Fp1+Fp2+Fz+F3+F4) | 7.3 | 2.2 | 3.24x | GOOD |

All virtual channel groups discriminate eyes-closed vs eyes-open with ratios 2.2–3.2x.

## Key Findings

### 1. Virtual channels carry real spatial information
Occipital alpha at ZUNA's virtual O1+O2 shows 2.54x EC/EO ratio — classic alpha blocking at electrodes Muse doesn't physically have. This is not random noise.

### 2. ZUNA improves frontal discrimination
Original frontal alpha ratio: 1.15x (barely detectable). After ZUNA: 1.64x. The diffusion model denoises and sharpens spectral features.

### 3. ZUNA reduces temporal raw power
Temporal EC/EO drops from 3.68x → 1.97x. The diffusion model normalizes toward its training distribution, compressing large amplitude differences. Still discriminative, but attenuated.

### 4. NOT useful for event detection (blinks, clenches)
Separate analysis showed ZUNA attenuates large deflections by 50-70% (blink at AF7: -813µV → -246µV). The model treats transient events as artifacts. **Do not use ZUNA output for blink/clench detection.**

### 5. Useful for spectral/BCI features
The virtual channels add genuine spatial diversity for band-power-based metrics:
- Concentration/relaxation (theta/beta ratio) at multiple scalp locations
- Alpha blocking for eyes-open/closed state detection
- Potentially: asymmetry metrics (e.g., frontal alpha asymmetry for valence)

## Real-Time Viability

| Config | Time for 60s data | Real-time ratio |
|--------|-------------------|----------------|
| First run (JIT compile) | 73s | 1.22x |
| Cached, 50 steps | 34s | 0.57x |
| Cached, 10 steps | 32s | 0.54x |

**Real-time viable on RTX 5090** with cached kernels (0.57x). Bottleneck is subprocess/model loading overhead, not diffusion steps. A persistent process feeding 5s chunks would be faster.

## Limitations

- Only 4 input channels (96% dropout for standard 10-20). ZUNA was trained on 19+ channel data.
- Virtual channel signals are model reconstructions, not direct measurements. They reflect what the diffusion model *expects* given the 4 real channels.
- Inter-channel correlations of virtual channels (mean=0.15) are lower than typical real EEG (0.5-0.8 for adjacent electrodes), suggesting partial hallucination mixed with real spatial inference.
- Single subject, single session. Needs replication.

## Conclusion

ZUNA superresolution from 4 Muse channels produces spatially meaningful virtual channels for **spectral features** (band powers, alpha blocking). It does NOT help with **event detection** (blinks, clenches). The virtual channels are best understood as "what a 19-channel EEG probably looked like given these 4 channels" — useful for state classification, not for detecting transient neural/muscular events.
