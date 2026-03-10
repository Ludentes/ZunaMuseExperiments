# Subagent Design Notes

Accumulating knowledge about recurring tasks that would benefit from specialized subagents.

## 1. Recording Quality Checker

**Trigger:** After recording a session, or on demand for a directory of recordings.

**Tasks:**
- Load .npz files, check channel count, sample rate, duration
- Compute per-channel stats: mean, std, min, max, RMS
- Flag anomalies: saturated samples (±1000µV), flat channels, extreme drift
- Check for expected events (blink deflections in blink trials, etc.)
- Report summary: "20 trials, 18 good, 2 with saturation on TP9"

**Inputs:** Directory path (e.g., `recordings/single_blink/`)
**Outputs:** Structured summary (text or JSON)

**Recurring patterns observed:**
- We manually check npz files after each recording session
- We look at channel ranges to validate data quality
- We run basic signal stats (RMS, min/max) to detect issues
- We check for glasses-falling-off artifacts (sudden drift/saturation)

## 2. Detector Evaluation Runner

**Trigger:** After modifying detector code, or after recording new data.

**Tasks:**
- Run `scripts/eval_blink_detector.py` with appropriate flags
- Parse output for precision/recall/F1
- Compare against previous experiment results in registry.csv
- Report delta: "F1: 0.95 → 0.96 (+0.01)"

**Inputs:** Detector name, optional recording subset
**Outputs:** Metrics comparison table

## 3. ZUNA Pipeline Runner

**Trigger:** When user wants to run ZUNA on recordings.

**Tasks:**
- Validate input files (duration ≥ 5s, montage set)
- Concatenate short trials if needed (e.g., 3s blink trials → 15s+ chunks)
- Run ZUNA preprocessing → inference → pt_to_fif
- Extract original 4 channels from reconstructed output for comparison
- Report timing stats for real-time viability assessment

**Inputs:** Recording directory or specific .fif files
**Outputs:** Reconstructed .fif files + timing report
