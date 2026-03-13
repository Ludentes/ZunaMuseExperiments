"""Evaluate BrainFlow's built-in detect_peaks_z_score for blink detection.

Tests BrainFlow's z-score peak detector against the same recorded blink/rest
data used by our custom BlinkDetector evaluation. Sweeps over parameter
combinations (lag, threshold, influence) and reports per-session and overall
precision/recall/F1.

Usage:
    PYTHONPATH=. python scripts/eval_brainflow_blink.py
"""
import glob
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
from brainflow.data_filter import DataFilter


# --- Data loading (matches eval_blink_detector.py) ---

def _load_npz(path: str) -> dict | None:
    try:
        d = np.load(path)
        eeg = d["eeg"]
        if eeg.size == 0 or eeg.ndim != 2:
            return None
        return {
            "eeg": eeg.astype(np.float64),
            "sfreq": int(d["sfreq"]) if "sfreq" in d else 256,
            "path": path,
        }
    except Exception as e:
        print(f"  Error loading {path}: {e}")
        return None


def load_trials(label: str) -> list[dict]:
    """Load all npz trials for a label, including from session subdirs."""
    trials = []
    for f in sorted(glob.glob(f"recordings/{label}/{label}_t*.npz")):
        trials.append(_load_npz(f))
    for f in sorted(glob.glob(f"recordings/{label}/*/{label}_t*.npz")):
        trials.append(_load_npz(f))
    return [t for t in trials if t is not None]


def extract_session_date(path: str) -> str:
    """Extract session date (YYYYMMDD) from filename like label_tNN_YYYYMMDD_HHMMSS.npz."""
    m = re.search(r"_t\d+_(\d{8})_\d{6}\.npz$", path)
    if m:
        return m.group(1)
    return "unknown"


# --- BrainFlow peak detection ---

def detect_blinks_brainflow(
    eeg: np.ndarray,
    lag: int,
    threshold: float,
    influence: float,
    negate: bool,
    channel: str = "both",
) -> bool:
    """Run BrainFlow detect_peaks_z_score on frontal channels.

    Args:
        eeg: (4, samples) array [TP9, AF7, AF8, TP10]
        lag: moving average window size
        threshold: z-score threshold
        influence: peak influence on running mean (0-1)
        negate: if True, negate signal before detection (for negative deflections)
        channel: "af7", "af8", or "both" (OR logic)

    Returns:
        True if any peak detected.
    """
    channels = []
    if channel in ("af7", "both"):
        channels.append(1)  # AF7
    if channel in ("af8", "both"):
        channels.append(2)  # AF8

    for ch_idx in channels:
        sig = eeg[ch_idx].copy()
        if negate:
            sig = -sig
        # detect_peaks_z_score needs float64
        sig = sig.astype(np.float64)
        if len(sig) < lag + 1:
            continue
        try:
            peaks = DataFilter.detect_peaks_z_score(sig, lag, threshold, influence)
            if np.any(peaks != 0):
                return True
        except Exception:
            continue
    return False


# --- Evaluation ---

def evaluate_params(
    blink_trials: list[dict],
    rest_trials: list[dict],
    lag: int,
    threshold: float,
    influence: float,
    negate: bool,
    channel: str = "both",
) -> dict:
    """Evaluate one parameter combo across all trials."""
    tp = fp = fn = tn = 0

    for trial in blink_trials:
        detected = detect_blinks_brainflow(
            trial["eeg"], lag, threshold, influence, negate, channel
        )
        if detected:
            tp += 1
        else:
            fn += 1

    for trial in rest_trials:
        detected = detect_blinks_brainflow(
            trial["eeg"], lag, threshold, influence, negate, channel
        )
        if detected:
            fp += 1
        else:
            tn += 1

    p = tp / (tp + fp) if (tp + fp) > 0 else 0
    r = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0

    return {
        "lag": lag, "threshold": threshold, "influence": influence,
        "negate": negate, "channel": channel,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(p, 4), "recall": round(r, 4), "f1": round(f1, 4),
        "n_blink": len(blink_trials), "n_rest": len(rest_trials),
    }


def evaluate_by_session(
    blink_trials: list[dict],
    rest_trials: list[dict],
    lag: int,
    threshold: float,
    influence: float,
    negate: bool,
    channel: str = "both",
) -> dict[str, dict]:
    """Evaluate one parameter combo, broken down by session date."""
    # Group trials by session date
    blink_by_session: dict[str, list] = defaultdict(list)
    rest_by_session: dict[str, list] = defaultdict(list)

    for t in blink_trials:
        date = extract_session_date(t["path"])
        blink_by_session[date].append(t)
    for t in rest_trials:
        date = extract_session_date(t["path"])
        rest_by_session[date].append(t)

    all_dates = sorted(set(list(blink_by_session.keys()) + list(rest_by_session.keys())))
    results = {}
    for date in all_dates:
        results[date] = evaluate_params(
            blink_by_session.get(date, []),
            rest_by_session.get(date, []),
            lag, threshold, influence, negate, channel,
        )
    return results


def main():
    print("Loading recorded trials...")
    rest = load_trials("rest")
    single = load_trials("single_blink")
    double = load_trials("double_blink")
    clench = load_trials("clench")
    talk = load_trials("talk")

    blink_trials = single + double
    # For rest/negative class, include rest + clench + talk (same as our eval)
    negative_trials = rest + clench + talk

    print(f"  single_blink={len(single)}, double_blink={len(double)}, "
          f"rest={len(rest)}, clench={len(clench)}, talk={len(talk)}")
    print(f"  Total: {len(blink_trials)} blink trials, {len(negative_trials)} negative trials")

    # Parameter grid
    lags = [10, 20, 30, 50]
    thresholds = [2.0, 3.0, 4.0, 5.0]
    influences = [0.0, 0.3, 0.5]
    negate_options = [False, True]
    channel_options = ["both"]  # AF7+AF8 OR logic

    # Sweep all combos
    print(f"\n{'='*80}")
    print("PARAMETER SWEEP (all trials pooled)")
    print(f"{'='*80}")
    print(f"  {'Negate':<7s} {'Lag':>4s} {'Thresh':>7s} {'Infl':>5s}  "
          f"{'TP':>3s} {'FP':>3s} {'FN':>3s} {'TN':>3s}  "
          f"{'Prec':>6s} {'Rec':>6s} {'F1':>6s}")
    print(f"  {'-'*70}")

    all_results = []
    for negate in negate_options:
        for lag in lags:
            for thresh in thresholds:
                for infl in influences:
                    r = evaluate_params(
                        blink_trials, negative_trials,
                        lag, thresh, infl, negate, "both",
                    )
                    all_results.append(r)
                    print(f"  {'neg' if negate else 'raw':<7s} {lag:>4d} {thresh:>7.1f} {infl:>5.1f}  "
                          f"{r['tp']:>3d} {r['fp']:>3d} {r['fn']:>3d} {r['tn']:>3d}  "
                          f"{r['precision']:>6.2f} {r['recall']:>6.2f} {r['f1']:>6.2f}")

    # Top 10 by F1
    all_results.sort(key=lambda r: (-r["f1"], -r["precision"]))
    print(f"\n{'='*80}")
    print("TOP 10 PARAMETER COMBOS BY F1")
    print(f"{'='*80}")
    print(f"  {'#':>2s} {'Negate':<7s} {'Lag':>4s} {'Thresh':>7s} {'Infl':>5s}  "
          f"{'Prec':>6s} {'Rec':>6s} {'F1':>6s}  "
          f"{'TP':>3s}/{' Blink':>5s}  {'FP':>3s}/{' Neg':>4s}")
    for i, r in enumerate(all_results[:10]):
        print(f"  {i+1:>2d} {'neg' if r['negate'] else 'raw':<7s} {r['lag']:>4d} "
              f"{r['threshold']:>7.1f} {r['influence']:>5.1f}  "
              f"{r['precision']:>6.2f} {r['recall']:>6.2f} {r['f1']:>6.2f}  "
              f"{r['tp']:>3d}/{r['n_blink']:>5d}  {r['fp']:>3d}/{r['n_rest']:>4d}")

    # Per-session breakdown for top 3 combos
    print(f"\n{'='*80}")
    print("PER-SESSION BREAKDOWN (top 3 combos)")
    print(f"{'='*80}")
    for i, r in enumerate(all_results[:3]):
        label = f"{'neg' if r['negate'] else 'raw'} lag={r['lag']} thresh={r['threshold']} infl={r['influence']}"
        print(f"\n  Combo {i+1}: {label}  (overall F1={r['f1']:.2f})")
        print(f"  {'Session':>10s}  {'Blink':>5s} {'Neg':>4s}  "
              f"{'TP':>3s} {'FP':>3s} {'FN':>3s} {'TN':>3s}  "
              f"{'Prec':>6s} {'Rec':>6s} {'F1':>6s}")

        by_session = evaluate_by_session(
            blink_trials, negative_trials,
            r["lag"], r["threshold"], r["influence"], r["negate"], "both",
        )
        for date, sr in sorted(by_session.items()):
            n_blink = sr["tp"] + sr["fn"]
            n_neg = sr["fp"] + sr["tn"]
            print(f"  {date:>10s}  {n_blink:>5d} {n_neg:>4d}  "
                  f"{sr['tp']:>3d} {sr['fp']:>3d} {sr['fn']:>3d} {sr['tn']:>3d}  "
                  f"{sr['precision']:>6.2f} {sr['recall']:>6.2f} {sr['f1']:>6.2f}")

    # Also test per-channel (AF7 only, AF8 only) for the best combo
    if all_results:
        best = all_results[0]
        print(f"\n{'='*80}")
        print(f"PER-CHANNEL TEST (best combo: {'neg' if best['negate'] else 'raw'} "
              f"lag={best['lag']} thresh={best['threshold']} infl={best['influence']})")
        print(f"{'='*80}")
        for ch in ["af7", "af8", "both"]:
            r = evaluate_params(
                blink_trials, negative_trials,
                best["lag"], best["threshold"], best["influence"],
                best["negate"], ch,
            )
            print(f"  {ch:<5s}  TP={r['tp']:>3d} FP={r['fp']:>3d} FN={r['fn']:>3d} TN={r['tn']:>3d}  "
                  f"P={r['precision']:.2f} R={r['recall']:.2f} F1={r['f1']:.2f}")

    # Comparison summary
    print(f"\n{'='*80}")
    print("COMPARISON WITH CUSTOM BlinkDetector")
    print(f"{'='*80}")
    if all_results:
        best = all_results[0]
        print(f"  BrainFlow detect_peaks_z_score best:  F1={best['f1']:.2f} "
              f"(P={best['precision']:.2f} R={best['recall']:.2f})")
        print(f"    params: negate={'yes' if best['negate'] else 'no'}, "
              f"lag={best['lag']}, threshold={best['threshold']}, influence={best['influence']}")
    print(f"  Custom BlinkDetector (6-layer):       F1=0.88-0.95 (from eval history)")
    print(f"\n  Note: BrainFlow's z-score detector is a simple statistical peak finder.")
    print(f"  It has no clench guard, speech guard, shape validation, or template matching.")
    print(f"  False positives on clench/talk trials are expected without these guards.")


if __name__ == "__main__":
    main()
