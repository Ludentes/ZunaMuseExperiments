"""Analyze blink recordings to find optimal BlinkDetector parameters.

Examines:
1. Waveform statistics (amplitude, duration, HF ratio) per trial type
2. Full parameter sweep: threshold_uv, threshold_sd, max_hf_ratio, max_deflection_ms
3. Double-blink timing analysis (inter-blink interval)
4. Per-guard rejection analysis

Usage:
    PYTHONPATH=. python scripts/analyze_blink_params.py
"""
import glob
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt

from backend.pipeline.stages.detectors import BlinkDetector, SpeechDetector
from backend.pipeline.types import PipelineFrame


# ── Helpers ──────────────────────────────────────────────────────────

def load_trials(label: str) -> list[dict]:
    trials = []
    for f in sorted(glob.glob(f"recordings/{label}/{label}_t*.npz")):
        trials.append(_load_npz(f))
    for f in sorted(glob.glob(f"recordings/{label}/*/{label}_t*.npz")):
        trials.append(_load_npz(f))
    return [t for t in trials if t is not None]


def _load_npz(path: str) -> dict | None:
    try:
        d = np.load(path)
        eeg = d["eeg"]
        if eeg.size == 0 or eeg.ndim != 2:
            return None
        return {
            "eeg": eeg.astype(np.float64),
            "cue_time_ms": int(d["cue_time_ms"]) if "cue_time_ms" in d else 0,
            "sfreq": int(d["sfreq"]) if "sfreq" in d else 256,
            "path": path,
        }
    except Exception as e:
        print(f"  Error loading {path}: {e}")
        return None


def hf_rms(signal: np.ndarray, sfreq: int = 256) -> float:
    """RMS of 20-45 Hz band."""
    if len(signal) < 20:
        return 0.0
    sos = butter(4, [20, 45], btype="band", fs=sfreq, output="sos")
    filtered = sosfilt(sos, signal)
    return float(np.sqrt(np.mean(filtered ** 2)))


# ── Waveform analysis ───────────────────────────────────────────────

def analyze_waveforms(label: str, trials: list[dict]):
    """Extract blink waveform statistics from trials."""
    if not trials:
        return

    print(f"\n{'='*60}")
    print(f"WAVEFORM ANALYSIS: {label} ({len(trials)} trials)")
    print(f"{'='*60}")

    amplitudes = []
    durations_ms = []
    hf_ratios = []
    temporal_mins = []

    for trial in trials:
        eeg = trial["eeg"]
        sfreq = trial["sfreq"]
        frontal = (eeg[1] + eeg[2]) / 2.0
        temporal = (eeg[0] + eeg[3]) / 2.0

        # Amplitude
        min_val = float(np.min(frontal))
        amplitudes.append(min_val)
        temporal_mins.append(float(np.min(temporal)))

        # Duration: contiguous samples below half-peak
        min_idx = int(np.argmin(frontal))
        half_amp = min_val / 2.0
        left = 0
        for i in range(min_idx - 1, -1, -1):
            if frontal[i] >= half_amp:
                break
            left += 1
        right = 0
        for i in range(min_idx + 1, len(frontal)):
            if frontal[i] >= half_amp:
                break
            right += 1
        dur_samples = left + 1 + right
        durations_ms.append(dur_samples / sfreq * 1000)

        # HF ratio (temporal / frontal)
        f_hf = hf_rms(frontal, sfreq)
        t_hf = hf_rms(temporal, sfreq)
        if f_hf > 0:
            hf_ratios.append(t_hf / f_hf)

    amplitudes = np.array(amplitudes)
    durations_ms = np.array(durations_ms)
    hf_ratios = np.array(hf_ratios)
    temporal_mins = np.array(temporal_mins)

    print(f"  Frontal amplitude (µV):  min={amplitudes.min():.1f}  p5={np.percentile(amplitudes, 5):.1f}  "
          f"median={np.median(amplitudes):.1f}  p95={np.percentile(amplitudes, 95):.1f}  max={amplitudes.max():.1f}")
    print(f"  Temporal amplitude (µV): min={temporal_mins.min():.1f}  median={np.median(temporal_mins):.1f}  max={temporal_mins.max():.1f}")
    print(f"  Deflection duration (ms): min={durations_ms.min():.0f}  p5={np.percentile(durations_ms, 5):.0f}  "
          f"median={np.median(durations_ms):.0f}  p95={np.percentile(durations_ms, 95):.0f}  max={durations_ms.max():.0f}")
    if len(hf_ratios) > 0:
        print(f"  HF ratio (T/F):          min={hf_ratios.min():.2f}  median={np.median(hf_ratios):.2f}  "
              f"p95={np.percentile(hf_ratios, 95):.2f}  max={hf_ratios.max():.2f}")


# ── Double-blink timing ─────────────────────────────────────────────

def analyze_double_blink_timing(trials: list[dict]):
    """Find inter-blink intervals in double-blink recordings."""
    if not trials:
        return

    print(f"\n{'='*60}")
    print(f"DOUBLE-BLINK TIMING ({len(trials)} trials)")
    print(f"{'='*60}")

    ibis = []  # inter-blink intervals in ms

    for trial in trials:
        eeg = trial["eeg"]
        sfreq = trial["sfreq"]
        frontal = (eeg[1] + eeg[2]) / 2.0

        # Find peaks (negative deflections) using a simple approach:
        # threshold at 50% of the trial's minimum, then find zero-crossings
        min_val = float(np.min(frontal))
        if min_val >= -30:
            continue  # no clear blink

        threshold = min_val * 0.4  # 40% of peak
        below = frontal < threshold

        # Find contiguous regions below threshold
        peaks = []
        in_region = False
        region_start = 0
        for i, b in enumerate(below):
            if b and not in_region:
                in_region = True
                region_start = i
            elif not b and in_region:
                in_region = False
                # Peak is the minimum within this region
                region = frontal[region_start:i]
                peak_idx = region_start + int(np.argmin(region))
                peaks.append(peak_idx)

        if len(peaks) >= 2:
            for j in range(1, len(peaks)):
                ibi_ms = (peaks[j] - peaks[j-1]) / sfreq * 1000
                if 100 < ibi_ms < 2000:  # reasonable range
                    ibis.append(ibi_ms)
            print(f"  {Path(trial['path']).name}: {len(peaks)} peaks, "
                  f"IBIs={[f'{(peaks[j]-peaks[j-1])/sfreq*1000:.0f}ms' for j in range(1, len(peaks))]}")
        else:
            print(f"  {Path(trial['path']).name}: only {len(peaks)} peak(s) found (min={min_val:.0f} µV)")

    if ibis:
        ibis = np.array(ibis)
        print(f"\n  Inter-blink intervals: min={ibis.min():.0f}  median={np.median(ibis):.0f}  "
              f"p95={np.percentile(ibis, 95):.0f}  max={ibis.max():.0f} ms")
        print(f"  → Recommended refractory_ms: {max(100, ibis.min() * 0.7):.0f}")
        print(f"  → Recommended classify_window_ms: {ibis.max() + 200:.0f}")


# ── Per-guard rejection analysis ──────────────────────────────────

def analyze_guard_rejections(label: str, trials: list[dict], expected_detect: bool):
    """Run detector with each guard individually disabled to find which blocks most."""
    if not trials:
        return

    configs = {
        "all_guards":    dict(threshold_uv=-50, threshold_sd=3.0, max_hf_ratio=4.5, max_deflection_ms=250, refractory_ms=200, classify_window_ms=1000),
        "no_clench":     dict(threshold_uv=-50, threshold_sd=3.0, max_hf_ratio=999, max_deflection_ms=250, refractory_ms=200, classify_window_ms=1000),
        "no_shape":      dict(threshold_uv=-50, threshold_sd=3.0, max_hf_ratio=4.5, max_deflection_ms=9999, refractory_ms=200, classify_window_ms=1000),
        "no_adaptive":   dict(threshold_uv=-50, threshold_sd=99,  max_hf_ratio=4.5, max_deflection_ms=250, refractory_ms=200, classify_window_ms=1000),
        "no_guards":     dict(threshold_uv=-50, threshold_sd=99,  max_hf_ratio=999, max_deflection_ms=9999, refractory_ms=200, classify_window_ms=1000),
        "loose_thresh":  dict(threshold_uv=-30, threshold_sd=2.0, max_hf_ratio=4.5, max_deflection_ms=250, refractory_ms=200, classify_window_ms=1000),
    }

    print(f"\n{'='*60}")
    print(f"GUARD ABLATION: {label} ({len(trials)} trials, expect_detect={expected_detect})")
    print(f"{'='*60}")

    for config_name, params in configs.items():
        detected = 0
        total_events = 0
        for trial in trials:
            events = _run_with_params(trial, params)
            blink_events = [e for e in events if "blink" in e]
            if blink_events:
                detected += 1
            total_events += len(blink_events)
        rate = detected / len(trials) * 100
        mark = "✓" if (expected_detect and rate > 80) or (not expected_detect and rate < 10) else "✗"
        print(f"  {mark} {config_name:15s}: {detected:2d}/{len(trials)} detected ({rate:5.1f}%), total_events={total_events}")


def _run_with_params(trial: dict, params: dict) -> list[str]:
    speech_detector = SpeechDetector()
    detector = BlinkDetector(**params)
    eeg = trial["eeg"]
    sfreq = trial["sfreq"]
    chunk_samples = max(4, sfreq // 60)

    all_events = []
    t = 0.0

    for start in range(0, eeg.shape[1], chunk_samples):
        end = min(start + chunk_samples, eeg.shape[1])
        chunk = eeg[:, start:end]
        frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
        speech_detector.process(frame)
        detector.process(frame)
        all_events.extend(frame.events)
        t += (end - start) / sfreq

    # Flush
    flush_eeg = np.zeros((4, 4), dtype=np.float64)
    frame = PipelineFrame(eeg=flush_eeg, ppg=None, imu=None, timestamp=t + 2.0)
    speech_detector.process(frame)
    detector.process(frame)
    all_events.extend(frame.events)

    return [e.kind for e in all_events]


# ── Full parameter sweep ────────────────────────────────────────────

def parameter_sweep(rest, single, double, clench, talk):
    """Sweep key parameters and find optimal combo."""
    print(f"\n{'='*60}")
    print("PARAMETER SWEEP")
    print(f"{'='*60}")

    thresholds_uv = [-30, -40, -50, -60, -75]
    thresholds_sd = [2.0, 2.5, 3.0, 3.5, 4.0]
    hf_ratios = [3.5, 4.5, 6.0, 999]
    deflection_ms = [150, 200, 250, 300, 9999]

    best_f1 = 0
    best_params = {}
    results = []

    positives = single + double
    negatives = rest + clench + talk

    # Coarse sweep: threshold_uv × threshold_sd (fix other params)
    print("\n  Phase 1: threshold_uv × threshold_sd sweep")
    print(f"  {'thresh_uv':>10s} {'thresh_sd':>10s} {'P':>6s} {'R':>6s} {'F1':>6s} {'TP':>4s} {'FP':>4s} {'FN':>4s}")

    for t_uv in thresholds_uv:
        for t_sd in thresholds_sd:
            params = dict(threshold_uv=t_uv, threshold_sd=t_sd, max_hf_ratio=4.5,
                          max_deflection_ms=250, refractory_ms=200, classify_window_ms=1000)
            tp, fp, fn = _eval_params(positives, negatives, params)
            p = tp / (tp + fp) if (tp + fp) > 0 else 0
            r = tp / (tp + fn) if (tp + fn) > 0 else 0
            f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0
            results.append((f1, params.copy()))
            if f1 > best_f1:
                best_f1 = f1
                best_params = params.copy()
            print(f"  {t_uv:>10d} {t_sd:>10.1f} {p:>6.2f} {r:>6.2f} {f1:>6.2f} {tp:>4d} {fp:>4d} {fn:>4d}")

    # Phase 2: refine with guard params using best threshold
    print(f"\n  Phase 2: guard parameter sweep (thresh_uv={best_params['threshold_uv']}, thresh_sd={best_params['threshold_sd']})")
    print(f"  {'hf_ratio':>10s} {'defl_ms':>10s} {'P':>6s} {'R':>6s} {'F1':>6s} {'TP':>4s} {'FP':>4s} {'FN':>4s}")

    for hf in hf_ratios:
        for defl in deflection_ms:
            params = dict(threshold_uv=best_params['threshold_uv'],
                          threshold_sd=best_params['threshold_sd'],
                          max_hf_ratio=hf, max_deflection_ms=defl,
                          refractory_ms=200, classify_window_ms=1000)
            tp, fp, fn = _eval_params(positives, negatives, params)
            p = tp / (tp + fp) if (tp + fp) > 0 else 0
            r = tp / (tp + fn) if (tp + fn) > 0 else 0
            f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0
            if f1 > best_f1:
                best_f1 = f1
                best_params = params.copy()
            print(f"  {hf:>10.1f} {defl:>10.0f} {p:>6.2f} {r:>6.2f} {f1:>6.2f} {tp:>4d} {fp:>4d} {fn:>4d}")

    print(f"\n  BEST: F1={best_f1:.3f}")
    for k, v in best_params.items():
        print(f"    {k}: {v}")

    return best_params, best_f1


def _eval_params(positives, negatives, params):
    tp = fp = fn = 0
    for trial in positives:
        events = _run_with_params(trial, params)
        if any("blink" in e for e in events):
            tp += 1
        else:
            fn += 1
    for trial in negatives:
        events = _run_with_params(trial, params)
        if any("blink" in e for e in events):
            fp += 1
    return tp, fp, fn


# ── Double-blink classification accuracy ────────────────────────────

def eval_double_blink_classification(single_trials, double_trials, params):
    """Check if detector correctly classifies single vs double."""
    print(f"\n{'='*60}")
    print("DOUBLE-BLINK CLASSIFICATION ACCURACY")
    print(f"{'='*60}")

    single_correct = 0
    single_as_double = 0
    single_missed = 0
    for trial in single_trials:
        events = _run_with_params(trial, params)
        blinks = [e for e in events if "blink" in e]
        if not blinks:
            single_missed += 1
        elif any("single" in e for e in blinks):
            single_correct += 1
        elif any("double" in e for e in blinks):
            single_as_double += 1
        else:
            single_correct += 1  # triple or other

    double_correct = 0
    double_as_single = 0
    double_missed = 0
    for trial in double_trials:
        events = _run_with_params(trial, params)
        blinks = [e for e in events if "blink" in e]
        if not blinks:
            double_missed += 1
        elif any("double" in e for e in blinks):
            double_correct += 1
        elif any("single" in e for e in blinks):
            double_as_single += 1
        else:
            double_correct += 1

    print(f"  Single blink trials ({len(single_trials)}):")
    print(f"    Correct (single): {single_correct}  Misclassified (double): {single_as_double}  Missed: {single_missed}")
    print(f"  Double blink trials ({len(double_trials)}):")
    print(f"    Correct (double): {double_correct}  Misclassified (single): {double_as_single}  Missed: {double_missed}")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    print("Loading recorded trials...")
    rest = load_trials("rest")
    single = load_trials("single_blink")
    double = load_trials("double_blink")
    clench = load_trials("clench")
    talk = load_trials("talk")
    triple = load_trials("triple_blink")

    print(f"  rest={len(rest)}, single={len(single)}, double={len(double)}, "
          f"triple={len(triple)}, clench={len(clench)}, talk={len(talk)}")

    # 1. Waveform analysis per type
    for label, trials in [("single_blink", single), ("double_blink", double),
                           ("rest", rest), ("clench", clench), ("talk", talk)]:
        analyze_waveforms(label, trials)

    # 2. Double-blink timing
    analyze_double_blink_timing(double)

    # 3. Guard ablation
    analyze_guard_rejections("single_blink", single, expected_detect=True)
    analyze_guard_rejections("double_blink", double, expected_detect=True)
    analyze_guard_rejections("rest", rest, expected_detect=False)
    analyze_guard_rejections("clench", clench, expected_detect=False)

    # 4. Parameter sweep
    best_params, best_f1 = parameter_sweep(rest, single, double, clench, talk)

    # 5. Double-blink classification
    eval_double_blink_classification(single, double, best_params)

    print(f"\n{'='*60}")
    print("RECOMMENDED DETECTOR CONFIG")
    print(f"{'='*60}")
    for k, v in best_params.items():
        print(f"  {k} = {v}")
    print(f"  F1 = {best_f1:.3f}")


if __name__ == "__main__":
    main()
