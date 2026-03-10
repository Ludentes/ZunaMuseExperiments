# SSVEP Experiment Results — 2026-03-10

## Experiment Setup

| Parameter | Value |
|-----------|-------|
| Headband | Muse 2 EEG (4ch: TP9, AF7, AF8, TP10, 256Hz) |
| Superresolution | ZUNA v0.1.1 (4 → 23ch, including virtual O1, O2) |
| Monitor | 3440x1440 @ 59.97Hz (all target frequencies divide cleanly) |
| Stimulus | Full-screen checkerboard with red fixation cross |
| Conditions | Control (static), 6Hz, 7.5Hz, 10Hz, 15Hz flicker |
| Trials | 10 trials x 15s per condition |

## Main Result: SSVEP Not Detected

No condition showed SNR > 1.0 at the target frequency on any channel (raw or ZUNA-reconstructed).

| Threshold | Detection Rate |
|-----------|---------------|
| SNR > 1.5 | 0% |
| SNR > 2.0 | 0% |
| SNR > 3.0 | 0% |

ZUNA virtual O1/O2 channels did not help. All SNR values ranged 0.5-0.8.

## Positive Finding: 6Hz Photic Driving at AF7

The `ssvep_6hz` condition produced a clear frequency-specific response at AF7:

| Metric | Value |
|--------|-------|
| AF7 power at 6Hz | 86.2 uV^2/Hz |
| Control power at 6Hz | 11.5 uV^2/Hz |
| Power increase | 7.5x |
| AF7 top spectral peaks | 5.9, 6.0, 6.1 Hz |
| Measured SNR | 0.78 (low due to high surrounding 4-5Hz power from eye/blink artifacts) |

This is **not SSVEP** — the signal is at frontal AF7, not occipital. It is likely a photic driving response or stimulus-locked eye artifact. AF8 did not show the same pattern, suggesting asymmetry from head/gaze positioning. Other frequencies (7.5, 10, 15Hz) did not produce similar clear peaks.

## Other Observations from Raw FFT

| Condition | Channel | Notable Peak | Interpretation |
|-----------|---------|-------------|----------------|
| ssvep_7hz | AF7 | 157 uV^2/Hz at 5.0-5.2Hz | Eye movement artifacts, not at target 7.5Hz |
| ssvep_15hz | TP9 | 10.1Hz (SNR=1.69) | Natural alpha rhythm, not SSVEP |
| ssvep_10hz | all | No signal at target | — |
| ssvep_none | AF8 | 6Hz (SNR=2.39) | Anomalous; possible persistent artifact |

All conditions showed dominant power at 4.0-4.5Hz (delta/low theta — general artifact and baseline brain activity).

## Why SSVEP Failed

1. **Electrode placement**: Muse electrodes (frontal/temporal) cannot see occipital SSVEP signals. Volume conduction from visual cortex is too weak.
2. **ZUNA smoothing**: The diffusion model reconstructs patterns it expects from training data. Narrow spectral peaks at specific frequencies are not natural EEG patterns and are likely smoothed away.
3. **Physics**: Volume conduction from visual cortex to frontal/temporal channels attenuates the signal below noise floor.

## Conclusion

SSVEP is not viable on Muse 2, with or without ZUNA superresolution. This confirms the assessment in [practical BCI commands](2026-03-08-muse2-practical-bci-commands.md).

However, the 6Hz photic driving response at AF7 (7.5x power increase) shows that frequency-tagged visual stimuli can produce detectable frontal signals — through eye/attention artifacts rather than cortical SSVEP. This may be exploitable for binary attention detection.
