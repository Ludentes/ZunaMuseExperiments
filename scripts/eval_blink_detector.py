"""Evaluate BlinkDetector on recorded experiment data.

Tests amplitude-threshold blink detector on:
- rest trials (should NOT detect blinks → false positives)
- single_blink trials (should detect 1 blink → true positives)
- double_blink trials (should detect 2 blinks → true positives)
- clench trials (should NOT detect blinks → false positives from jaw)
- talk trials (should NOT detect blinks → false positives from speech)

Also tests across threshold values to find optimal setting.

Usage:
    PYTHONPATH=. python scripts/eval_blink_detector.py [--save] [--name NAME] [--tag TAG]
"""
import argparse
import glob
import io
import time
from pathlib import Path

import numpy as np

from backend.pipeline.stages.detectors import BlinkDetector, SpeechDetector
from backend.pipeline.types import PipelineFrame


def load_trials(label: str) -> list[dict]:
    """Load all npz trials for a label, including from session subdirs."""
    trials = []
    # Direct files
    for f in sorted(glob.glob(f"recordings/{label}/{label}_t*.npz")):
        trials.append(_load_npz(f))
    # Session subdirectories
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


def run_detector_on_trial(trial: dict, threshold: float) -> list[str]:
    """Run BlinkDetector on a trial, simulating ~16ms polling chunks.

    Returns list of detected event kinds.
    """
    speech_detector = SpeechDetector()
    detector = BlinkDetector(
        threshold_uv=threshold,
        refractory_ms=300,
        classify_window_ms=800,
    )
    eeg = trial["eeg"]
    sfreq = trial["sfreq"]
    chunk_samples = max(4, sfreq // 60)  # ~16ms chunks at 256Hz ≈ 4 samples

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

    # Final flush: run one more empty-ish frame well after last data
    flush_eeg = np.zeros((4, 4), dtype=np.float64)
    frame = PipelineFrame(eeg=flush_eeg, ppg=None, imu=None, timestamp=t + 2.0)
    speech_detector.process(frame)
    detector.process(frame)
    all_events.extend(frame.events)

    return [e.kind for e in all_events]


def evaluate(label: str, trials: list[dict], threshold: float,
             expected_blinks: int) -> dict:
    """Evaluate detector on a set of trials.

    For blink trials: expected_blinks > 0, check if detected count matches.
    For non-blink trials: expected_blinks == 0, any detection is false positive.
    """
    tp = 0  # correct detection
    fp = 0  # false positive (detected when shouldn't, or wrong count)
    fn = 0  # missed (should detect but didn't)
    tn = 0  # correct rejection

    details = []

    for trial in trials:
        events = run_detector_on_trial(trial, threshold)
        blink_events = [e for e in events if "blink" in e]
        n_detected = len(blink_events)

        if expected_blinks == 0:
            # Non-blink trial
            if n_detected == 0:
                tn += 1
            else:
                fp += 1
                details.append(f"  FP: {Path(trial['path']).name} → {blink_events}")
        else:
            # Blink trial
            if n_detected > 0:
                tp += 1
                if n_detected != 1:  # multiple events is suspicious
                    details.append(f"  MULTI: {Path(trial['path']).name} → {blink_events}")
            else:
                fn += 1
                details.append(f"  FN: {Path(trial['path']).name} → no detection")

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision, "recall": recall, "f1": f1,
        "details": details, "total": len(trials),
    }


def print_results(label: str, results: dict):
    print(f"  {label:15s}  n={results['total']:2d}  "
          f"TP={results['tp']:2d} FP={results['fp']:2d} "
          f"FN={results['fn']:2d} TN={results['tn']:2d}  "
          f"P={results['precision']:.2f} R={results['recall']:.2f} F1={results['f1']:.2f}")
    for d in results["details"][:5]:
        print(d)


def sweep_threshold(rest, single, double, clench, talk, thresh):
    """Run full eval at one threshold, return summary dict."""
    tp = fp = fn = tn = 0
    fp_rest = fp_clench = fp_talk = 0

    for trial in single + double:
        events = run_detector_on_trial(trial, thresh)
        if any("blink" in e for e in events):
            tp += 1
        else:
            fn += 1

    for label_trials, counter_name in [(rest, "rest"), (clench, "clench"), (talk, "talk")]:
        for trial in label_trials:
            events = run_detector_on_trial(trial, thresh)
            if any("blink" in e for e in events):
                fp += 1
                if counter_name == "rest": fp_rest += 1
                elif counter_name == "clench": fp_clench += 1
                else: fp_talk += 1
            else:
                tn += 1

    p = tp / (tp + fp) if (tp + fp) > 0 else 0
    r = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0

    return {
        "threshold": thresh, "precision": round(p, 4), "recall": round(r, 4),
        "f1": round(f1, 4), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "fp_rest": fp_rest, "fp_clench": fp_clench, "fp_talk": fp_talk,
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate blink detector")
    parser.add_argument("--save", action="store_true", help="Save results to experiments/")
    parser.add_argument("--name", default="blink-detector-eval", help="Experiment name")
    parser.add_argument("--tag", action="append", default=[], help="Tags (repeatable)")
    args = parser.parse_args()

    # Capture output for artifact saving
    output = io.StringIO()
    def tee(s: str = ""):
        print(s)
        output.write(s + "\n")

    tee("Loading recorded trials...")
    rest = load_trials("rest")
    single = load_trials("single_blink")
    double = load_trials("double_blink")
    clench = load_trials("clench")
    talk = load_trials("talk")
    tee(f"  rest={len(rest)}, single_blink={len(single)}, double_blink={len(double)}, "
        f"clench={len(clench)}, talk={len(talk)}")

    # Quick signal check
    tee(f"\n{'='*60}")
    tee("SIGNAL CHECK: min(AF7+AF8)/2 per trial type")
    tee(f"{'='*60}")
    for label, trials in [("rest", rest), ("single_blink", single),
                           ("double_blink", double), ("clench", clench), ("talk", talk)]:
        if not trials:
            tee(f"  {label}: no data")
            continue
        mins = [float(np.min((t["eeg"][1] + t["eeg"][2]) / 2.0)) for t in trials]
        tee(f"  {label:15s}  min={np.min(mins):8.1f}  mean_min={np.mean(mins):8.1f}  "
            f"max_min={np.max(mins):8.1f} µV")

    thresholds = [-50, -75, -100, -125, -150, -200]

    # Per-threshold detailed results
    for thresh in thresholds:
        tee(f"\n{'='*60}")
        tee(f"THRESHOLD = {thresh} µV")
        tee(f"{'='*60}")
        if rest:
            r = evaluate("rest", rest, thresh, expected_blinks=0)
            print_results("rest (neg)", r)
        if single:
            r = evaluate("single_blink", single, thresh, expected_blinks=1)
            print_results("single (pos)", r)
        if double:
            r = evaluate("double_blink", double, thresh, expected_blinks=1)
            print_results("double (pos)", r)
        if clench:
            r = evaluate("clench", clench, thresh, expected_blinks=0)
            print_results("clench (neg)", r)
        if talk:
            r = evaluate("talk", talk, thresh, expected_blinks=0)
            print_results("talk (neg)", r)

    # Sweep summary
    tee(f"\n{'='*60}")
    tee("THRESHOLD SWEEP SUMMARY")
    tee(f"{'='*60}")
    tee(f"  {'Thresh':>8s}  {'Precision':>9s}  {'Recall':>6s}  {'F1':>6s}  "
        f"{'FP_rest':>7s}  {'FP_clench':>9s}  {'FP_talk':>7s}")

    sweep_results = []
    for thresh in thresholds:
        row = sweep_threshold(rest, single, double, clench, talk, thresh)
        sweep_results.append(row)
        tee(f"  {row['threshold']:>7d}  {row['precision']:>9.2f}  {row['recall']:>6.2f}  "
            f"{row['f1']:>6.2f}  {row['fp_rest']:>7d}  {row['fp_clench']:>9d}  "
            f"{row['fp_talk']:>7d}")

    # Find best threshold by F1
    best = max(sweep_results, key=lambda r: r["f1"])
    tee(f"\nBest threshold: {best['threshold']} µV  "
        f"(P={best['precision']:.2f} R={best['recall']:.2f} F1={best['f1']:.2f})")

    # Save experiment if requested
    if args.save:
        from scripts.experiment import Experiment

        with Experiment(args.name, tags=args.tag or ["blink"]) as exp:
            exp.params({
                "threshold_uv": best["threshold"],
                "threshold_sd": 4.0,
                "max_hf_ratio": 3.5,
                "hf_window_samples": 128,
                "max_deflection_ms": 200,
                "refractory_ms": 300,
                "classify_window_ms": 800,
                "n_rest": len(rest),
                "n_single": len(single),
                "n_double": len(double),
                "n_clench": len(clench),
                "n_talk": len(talk),
            })
            exp.metrics({
                "best_f1": best["f1"],
                "best_precision": best["precision"],
                "best_recall": best["recall"],
                "best_threshold": best["threshold"],
                "fp_rest": best["fp_rest"],
                "fp_clench": best["fp_clench"],
                "fp_talk": best["fp_talk"],
            })
            exp.artifact("full_output.txt", output.getvalue())


if __name__ == "__main__":
    main()
