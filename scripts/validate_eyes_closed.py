#!/usr/bin/env python3
"""Validate alpha blocking on existing recordings.

Computes frontal alpha power ratios on eyes_closed, eyes_open, and rest
recordings to determine if the raw signal can distinguish eyes-closed
from eyes-open — and what threshold works for real-time detection.

Usage:
    PYTHONPATH=. python scripts/validate_eyes_closed.py
"""
from glob import glob
from pathlib import Path

import numpy as np
from brainflow.data_filter import (
    DataFilter,
    DetrendOperations,
    WindowOperations,
)

SFREQ = 256
ALPHA_LOW = 7.5
ALPHA_HIGH = 13.0


def compute_frontal_alpha(eeg: np.ndarray, sfreq: int = SFREQ) -> float:
    """Compute mean frontal alpha power from AF7 (ch1) and AF8 (ch2).

    Args:
        eeg: (4, n_samples) EEG array in µV.
        sfreq: Sampling frequency.

    Returns:
        Mean alpha band power across AF7 and AF8 (µV²).
    """
    nfft = DataFilter.get_nearest_power_of_two(sfreq)
    powers = []
    for ch_idx in [1, 2]:  # AF7, AF8
        data = eeg[ch_idx].astype(np.float64).copy()
        DataFilter.detrend(data, DetrendOperations.LINEAR.value)
        psd = DataFilter.get_psd_welch(
            data, nfft, nfft // 2, sfreq, WindowOperations.HANNING.value
        )
        alpha_power = DataFilter.get_band_power(psd, ALPHA_LOW, ALPHA_HIGH)
        powers.append(alpha_power)
    return float(np.mean(powers))


def compute_sliding_alpha(
    eeg: np.ndarray,
    sfreq: int = SFREQ,
    window_s: float = 2.0,
    step_s: float = 0.5,
) -> list[float]:
    """Compute alpha power in sliding windows (real-time simulation).

    Args:
        eeg: (4, n_samples) EEG array.
        sfreq: Sampling frequency.
        window_s: Window length in seconds.
        step_s: Step size in seconds.

    Returns:
        List of alpha power values per window.
    """
    window = int(window_s * sfreq)
    step = int(step_s * sfreq)
    n_samples = eeg.shape[1]
    powers = []
    start = 0
    while start + window <= n_samples:
        chunk = eeg[:, start : start + window]
        powers.append(compute_frontal_alpha(chunk, sfreq))
        start += step
    return powers


def load_recordings(label: str) -> list[np.ndarray]:
    """Load all EEG arrays for a given label.

    Searches recordings/{label}/**/*.npz recursively.

    Returns:
        List of (4, n_samples) EEG arrays.
    """
    pattern = f"recordings/{label}/**/*.npz"
    paths = sorted(glob(pattern, recursive=True))
    if not paths:
        # Also try non-recursive (rest has flat structure)
        pattern = f"recordings/{label}/*.npz"
        paths = sorted(glob(pattern, recursive=True))
    arrays = []
    for p in paths:
        d = np.load(p, allow_pickle=True)
        arrays.append(d["eeg"])
        print(f"  Loaded {Path(p).name}: {d['eeg'].shape[1]} samples "
              f"({d['eeg'].shape[1] / SFREQ:.1f}s)")
    return arrays


def main():
    print("=" * 60)
    print("Eyes-Closed Alpha Blocking Validation")
    print("=" * 60)

    # --- Load recordings ---
    labels = ["eyes_closed", "eyes_open", "rest"]
    data: dict[str, list[np.ndarray]] = {}
    for label in labels:
        print(f"\n[{label}]")
        recordings = load_recordings(label)
        if not recordings:
            print(f"  WARNING: No recordings found for '{label}'")
        data[label] = recordings

    if not data["eyes_closed"] or not data["eyes_open"]:
        print("\nERROR: Need both eyes_closed and eyes_open recordings.")
        return

    # --- Overall alpha power per category ---
    print("\n" + "=" * 60)
    print("Overall Alpha Power (µV²)")
    print("=" * 60)

    category_powers: dict[str, list[float]] = {}
    for label, recordings in data.items():
        powers = [compute_frontal_alpha(rec) for rec in recordings]
        category_powers[label] = powers
        if powers:
            mean_p = np.mean(powers)
            std_p = np.std(powers)
            print(f"  {label:15s}: mean={mean_p:8.2f}  std={std_p:7.2f}  "
                  f"n={len(powers)} trials")

    ec_mean = np.mean(category_powers["eyes_closed"])
    eo_mean = np.mean(category_powers["eyes_open"])
    ratio = ec_mean / eo_mean if eo_mean > 0 else float("inf")
    print(f"\n  EC/EO ratio: {ratio:.2f}x")

    # --- Sliding window analysis ---
    print("\n" + "=" * 60)
    print("Sliding Window Analysis (2s window, 0.5s step)")
    print("=" * 60)

    window_powers: dict[str, list[float]] = {}
    for label, recordings in data.items():
        all_windows = []
        for rec in recordings:
            all_windows.extend(compute_sliding_alpha(rec))
        window_powers[label] = all_windows
        if all_windows:
            print(f"  {label:15s}: mean={np.mean(all_windows):8.2f}  "
                  f"std={np.std(all_windows):7.2f}  "
                  f"median={np.median(all_windows):8.2f}  "
                  f"n={len(all_windows)} windows")

    # --- Threshold analysis ---
    print("\n" + "=" * 60)
    print("Threshold Analysis")
    print("=" * 60)

    # Use rest or eyes_open as baseline
    if window_powers.get("rest"):
        baseline = np.mean(window_powers["rest"])
        baseline_label = "rest"
    else:
        baseline = np.mean(window_powers["eyes_open"])
        baseline_label = "eyes_open"
    print(f"  Baseline ({baseline_label}): {baseline:.2f} µV²\n")

    ec_windows = np.array(window_powers["eyes_closed"])
    eo_windows = np.array(window_powers["eyes_open"])

    multipliers = [1.2, 1.3, 1.5, 1.8, 2.0, 2.5]
    print(f"  {'Mult':>5s}  {'Thresh':>8s}  {'EC Det%':>8s}  {'EO FA%':>8s}  "
          f"{'EC>thr':>6s}  {'EO>thr':>6s}")
    print(f"  {'-' * 5}  {'-' * 8}  {'-' * 8}  {'-' * 8}  {'-' * 6}  {'-' * 6}")

    best_mult = None
    best_score = -1.0
    for mult in multipliers:
        threshold = baseline * mult
        ec_detect = float(np.mean(ec_windows > threshold) * 100)
        eo_fa = float(np.mean(eo_windows > threshold) * 100)
        n_ec = int(np.sum(ec_windows > threshold))
        n_eo = int(np.sum(eo_windows > threshold))
        print(f"  {mult:5.1f}  {threshold:8.2f}  {ec_detect:7.1f}%  "
              f"{eo_fa:7.1f}%  {n_ec:6d}  {n_eo:6d}")

        # Score: maximize detection - false alarm
        score = ec_detect - eo_fa
        if score > best_score:
            best_score = score
            best_mult = mult

    print(f"\n  Best multiplier: {best_mult}x "
          f"(detection - FA gap = {best_score:.1f}%)")
    print(f"  Recommended threshold: {baseline * best_mult:.2f} µV² "
          f"({best_mult}x {baseline_label} baseline)")

    # --- Distribution overlap ---
    print("\n" + "=" * 60)
    print("Distribution Summary")
    print("=" * 60)
    for label in ["eyes_closed", "eyes_open"]:
        w = window_powers[label]
        if w:
            pcts = np.percentile(w, [10, 25, 50, 75, 90])
            print(f"  {label:15s}: p10={pcts[0]:.1f}  p25={pcts[1]:.1f}  "
                  f"p50={pcts[2]:.1f}  p75={pcts[3]:.1f}  p90={pcts[4]:.1f}")


if __name__ == "__main__":
    main()
