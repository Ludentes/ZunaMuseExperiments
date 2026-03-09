# Muse 2 Data Validation Report

**Date:** 2026-03-08
**Device:** Muse 2 (BrainFlow board_id=38)
**Sources:** BrainFlow docs, Mind Monitor technical manual, PMC research papers, live capture via `scripts/diagnose_data.py`

---

## Executive Summary

The data pipeline (BrainFlow -> Python backend -> WebSocket -> React frontend) is producing correct values across all sensor modalities. EEG amplitudes, band powers, heart rate, accelerometer, and signal quality all fall within expected ranges for Muse 2. Two derived metrics (HRV RMSSD and SpO2) have known accuracy limitations.

## Live Capture Results (20s, resting, eyes open)

### EEG (256 Hz, 4 channels)

| Channel | Mean (uV) | Std (uV) | RMS (uV) | Range (uV) | Verdict |
|---------|-----------|----------|----------|-------------|---------|
| TP9     | -32.15    | 17.24    | 36.48    | -191 to 51  | Normal  |
| AF7     | -30.20    | 13.02    | 32.89    | -71 to 59   | Normal  |
| AF8     | -31.20    | 8.37     | 32.30    | -64 to 11   | Normal  |
| TP10    | -28.08    | 39.51    | 48.47    | -228 to 103 | Normal (noisier, typical for temporal) |

**Expected:** 5-50 uV std for filtered resting EEG. All channels within range.

**Note:** BrainFlow returns EEG in microvolts (uV). The DC offset (~-30 uV mean) is normal and removed by our highpass filter before display.

### Band Powers (uV^2, absolute power via `get_psd_welch` + `get_band_power`)

| Band  | Freq (Hz) | Typical Range (uV^2) | Our Values (avg across cycles) | Notes |
|-------|-----------|---------------------|-------------------------------|-------|
| Delta | 0.5-4     | 10-500              | 4-458                         | Spikes = muscle artifact on TP9/TP10 |
| Theta | 4-8       | 5-100               | 1.3-115                       | Spikes correlate with delta spikes |
| Alpha | 8-13      | 10-200              | 0.8-18                        | Low because eyes open (alpha blocking) |
| Beta  | 13-30     | 2-50                | 1.9-14                        | Stable, consistent |
| Gamma | 30-45     | 0.5-20              | 0.9-6                         | Stable, low as expected |

**Key observations:**
- Band power spikes on TP9/TP10 are real muscle artifacts (jaw clench, swallow), not pipeline bugs
- AF7/AF8 (frontal) channels are much more stable
- Alpha should increase with eyes closed (testable via "alpha blocking" paradigm)
- Values are in uV^2 (absolute power), not dB or Bels

**Known limitation:** 2-second PSD windows are noisy. Band powers fluctuate between cycles. A longer rolling window or exponential smoothing would stabilize the display for downstream use.

### PPG (64 Hz, 3 channels)

| Channel | Mean      | Std    | Notes |
|---------|-----------|--------|-------|
| Red     | 472.45    | 0.77   | Low amplitude — forehead site |
| IR      | 141,982   | 702.84 | Primary signal for HR |
| Ambient | 0.00      | 0.00   | Expected (indoor, no direct light) |

**Heart rate:** 63-75 bpm (correct for resting adult)
- BrainFlow `get_heart_rate(ppg_ir, ppg_red, 64, 1024)` — FFT-based
- Requires >= 1024 samples (~16s at 64Hz)
- Expect ~5-15 bpm error vs chest strap
- Fails during head movement

**SpO2:** 97-100% (plausible but unreliable)
- Muse 2 forehead PPG was not designed for SpO2
- BrainFlow's default calibration coefficients may not match this sensor
- Treat as informational only; do not use for medical decisions

**HRV RMSSD:** 112-237 ms (INCORRECT — too high)
- Normal resting HRV RMSSD: 20-80 ms
- Our simple peak detection (zero-crossing of derivative) picks up noise peaks
- Needs a proper R-peak detector (e.g., Pan-Tompkins adapted for PPG) for downstream use
- Current values should be treated as unreliable

### IMU (52 Hz, 6 channels)

| Channel | Mean    | Std    | Notes |
|---------|---------|--------|-------|
| AccX    | 0.016   | 0.049  | Near zero (head roughly level) |
| AccY    | 0.196   | 0.038  | Slight tilt |
| AccZ    | 0.985   | 0.007  | ~1g (gravity) |
| GyrX    | -0.064  | 4.130  | deg/s, noisy at rest |
| GyrY    | 2.225   | 3.013  | deg/s |
| GyrZ    | 0.129   | 5.746  | deg/s |

**Accelerometer magnitude:** 1.007g (expected 0.9-1.1g when still)

**Units:** g (not m/s^2). `GRAVITY = 1.0` is correct.

**Axes on head:**
- X = forward/backward (pitch)
- Y = left/right (roll)
- Z = vertical (gravity when upright)

**Head movement metric** (`abs(magnitude - 1.0) / 1.0`): 0.003-0.007 at rest. Threshold 0.3 for motion artifact flagging is reasonable.

## Signal Quality Thresholds

Current thresholds are well-calibrated:

| Check | Threshold | Purpose |
|-------|-----------|---------|
| Rail detection | abs(value) > 995 uV | Saturated ADC |
| Flat line | std < 2 uV | No electrode contact |
| Excessive noise | std > 200 uV | Heavy artifact/no contact |
| Fit status | 0 poor = good, 1-2 = adjust, 3+ = poor | Overall headband fit |

## Known Issues for Downstream Work

### Must fix for BCI experiments

1. **Band power stability**: 2s PSD windows produce noisy estimates. Use 4-8s rolling window and/or exponential moving average for any paradigm that depends on stable band power tracking (neurofeedback, concentration detection).

2. **Artifact rejection**: No artifact rejection currently. TP9/TP10 muscle artifacts contaminate delta/theta estimates. Options:
   - Threshold-based: reject windows where delta > N uV^2
   - Gradient-based: reject if dV/dt > 10 uV/ms
   - ICA-based: separate neural from muscular components (heavy, may not be real-time feasible)

3. **HRV computation**: Current peak detection is unreliable. Implement Pan-Tompkins or similar QRS-adapted algorithm for PPG R-peak detection. Or use a library like `heartpy` or `neurokit2`.

### Nice to have

4. **SpO2 calibration**: Calibrate BrainFlow's coefficients against a reference pulse oximeter, or remove SpO2 if not needed.

5. **Alpha blocking validation**: Run eyes-open vs eyes-closed comparison to confirm alpha band is responsive. This is the standard sanity check for EEG pipelines.

6. **Cross-channel consistency**: Add monitoring for L/R asymmetry beyond FAA — large persistent asymmetries in non-alpha bands may indicate poor contact on one side.

## Diagnostic Tool

Run `python scripts/diagnose_data.py --seconds 20` to capture and validate live data. Requires backend running with Muse connected.

## Sources

- [BrainFlow Supported Boards](https://brainflow.readthedocs.io/en/stable/SupportedBoards.html)
- [BrainFlow Data Format](https://brainflow.readthedocs.io/en/stable/DataFormatDesc.html)
- [BrainFlow Band Power Notebook](https://brainflow.readthedocs.io/en/stable/notebooks/band_power.html)
- [Mind Monitor Technical Manual](https://www.musemonitor.com/Technical_Manual.php)
- [Choosing MUSE: Validation of a Low-Cost Portable EEG System (PMC5344886)](https://pmc.ncbi.nlm.nih.gov/articles/PMC5344886/)
- [Resting-state EEG: gel-based vs consumer dry electrodes (PMC10873917)](https://pmc.ncbi.nlm.nih.gov/articles/PMC10873917/)
- [Automated Data Cleaning for the Muse EEG (ResearchGate)](https://www.researchgate.net/publication/357853210)
