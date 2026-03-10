#!/usr/bin/env python3
"""Fz Neurofeedback Validation: 3-condition test (meditation vs drowsy vs mental_math).

Tests whether ZUNA's virtual Fz channel provides frontal midline theta (FMθ)
that distinguishes focused meditation from drowsy mind-wandering — something
raw Muse AF7/AF8 alpha cannot do.

Usage:
    PYTHONPATH=. python scripts/eval_fz_validation.py
"""
import shutil
import time
from pathlib import Path

import mne
import numpy as np
from scipy.signal import welch

mne.set_log_level("WARNING")

CHANNELS_TO_ADD_19 = [
    "Fp1", "Fp2", "F7", "F3", "Fz", "F4", "F8",
    "T3", "C3", "Cz", "C4", "T4",
    "T5", "P3", "Pz", "P4", "T6",
    "O1", "O2",
]


def band_power(data_uv: np.ndarray, sr: int, lo: float, hi: float) -> float:
    """Compute band power in µV² using Welch's method."""
    freqs, psd = welch(data_uv, fs=sr, nperseg=min(1024, len(data_uv)))
    idx = (freqs >= lo) & (freqs <= hi)
    return float(np.trapezoid(psd[idx], freqs[idx]))


def find_fif_files(label: str) -> list[Path]:
    """Find all raw .fif files for a label."""
    base = Path("recordings") / label
    files = sorted(base.rglob("*_raw.fif"))
    if not files:
        raise FileNotFoundError(f"No .fif files found in {base}")
    return files


def concat_fifs(files: list[Path]) -> mne.io.Raw:
    """Concatenate multiple .fif files into one Raw object."""
    raws = []
    for f in files:
        raw = mne.io.read_raw_fif(str(f), preload=True, verbose=False)
        raws.append(raw)
    combined = mne.concatenate_raws(raws)
    print(f"  Concatenated {len(files)} files -> {combined.times[-1]:.1f}s")
    return combined


def run_zuna(raw: mne.io.Raw, label: str) -> mne.io.Raw:
    """Run ZUNA pipeline on a Raw object, return reconstructed Raw."""
    from zuna import preprocessing, inference, pt_to_fif

    work_dir = Path(f"/tmp/zuna_{label}")
    if work_dir.exists():
        shutil.rmtree(work_dir)

    fif_input = work_dir / "0_fif_input"
    fif_input.mkdir(parents=True)
    input_path = fif_input / f"{label}_raw.fif"
    raw.save(str(input_path), overwrite=True, verbose=False)

    pt_input = str(work_dir / "2_pt_input")
    pt_output = str(work_dir / "3_pt_output")
    fif_output = str(work_dir / "4_fif_output")
    preprocessed = str(work_dir / "1_fif_filter")
    for d in [pt_input, pt_output, fif_output, preprocessed]:
        Path(d).mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    preprocessing(
        input_dir=str(fif_input),
        output_dir=pt_input,
        apply_notch_filter=True,
        apply_highpass_filter=True,
        apply_average_reference=False,
        target_channel_count=CHANNELS_TO_ADD_19,
        bad_channels=[],
        preprocessed_fif_dir=preprocessed,
    )

    inference(
        input_dir=pt_input,
        output_dir=pt_output,
        gpu_device="0",
        tokens_per_batch=100000,
        data_norm=10.0,
        diffusion_cfg=1.0,
        diffusion_sample_steps=50,
        plot_eeg_signal_samples=False,
        inference_figures_dir=str(work_dir / "figs"),
    )

    pt_to_fif(input_dir=pt_output, output_dir=fif_output)
    elapsed = time.time() - t0
    print(f"  ZUNA pipeline: {elapsed:.1f}s")

    out_files = sorted(Path(fif_output).glob("*.fif"))
    if not out_files:
        raise RuntimeError(f"ZUNA produced no output for {label}")
    return mne.io.read_raw_fif(str(out_files[0]), preload=True, verbose=False)


def cohens_d(a: np.ndarray, b: np.ndarray) -> float:
    """Compute Cohen's d (pooled std)."""
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return 0.0
    pooled = np.sqrt(((na - 1) * np.var(a, ddof=1) + (nb - 1) * np.var(b, ddof=1)) / (na + nb - 2))
    if pooled < 1e-10:
        return 0.0
    return float((np.mean(a) - np.mean(b)) / pooled)


def window_features(data_uv: np.ndarray, sr: int, ch_names: list[str], window_s: float) -> dict[str, list[float]]:
    """Slice data into non-overlapping windows and compute features per window."""
    n_samples = data_uv.shape[1]
    win_samples = int(window_s * sr)
    n_windows = n_samples // win_samples

    features: dict[str, list[float]] = {
        "fz_theta": [],
        "fz_beta": [],
        "fz_theta_beta": [],
        "af_alpha": [],
        "af_theta": [],
        "af_beta": [],
        "af_theta_beta": [],
    }

    fz_idx = ch_names.index("Fz") if "Fz" in ch_names else None
    af7_idx = ch_names.index("AF7") if "AF7" in ch_names else None
    af8_idx = ch_names.index("AF8") if "AF8" in ch_names else None

    for i in range(n_windows):
        start = i * win_samples
        end = start + win_samples

        if fz_idx is not None:
            fz_theta = band_power(data_uv[fz_idx, start:end], sr, 4, 8)
            fz_beta = band_power(data_uv[fz_idx, start:end], sr, 13, 30)
            features["fz_theta"].append(fz_theta)
            features["fz_beta"].append(fz_beta)
            features["fz_theta_beta"].append(fz_theta / max(fz_beta, 0.01))

        if af7_idx is not None and af8_idx is not None:
            af7_alpha = band_power(data_uv[af7_idx, start:end], sr, 8, 13)
            af8_alpha = band_power(data_uv[af8_idx, start:end], sr, 8, 13)
            af7_theta = band_power(data_uv[af7_idx, start:end], sr, 4, 8)
            af8_theta = band_power(data_uv[af8_idx, start:end], sr, 4, 8)
            af7_beta = band_power(data_uv[af7_idx, start:end], sr, 13, 30)
            af8_beta = band_power(data_uv[af8_idx, start:end], sr, 13, 30)
            features["af_alpha"].append((af7_alpha + af8_alpha) / 2)
            features["af_theta"].append((af7_theta + af8_theta) / 2)
            features["af_beta"].append((af7_beta + af8_beta) / 2)
            af_tb = (af7_theta + af8_theta) / max(af7_beta + af8_beta, 0.01)
            features["af_theta_beta"].append(af_tb)

    return features


def classification_accuracy(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """Find optimal threshold and return (accuracy, threshold)."""
    combined = np.concatenate([a, b])
    best_acc = 0.0
    best_thresh = 0.0
    for pct in range(5, 96):
        thresh = np.percentile(combined, pct)
        # Try both directions
        acc1 = (np.sum(a >= thresh) + np.sum(b < thresh)) / (len(a) + len(b))
        acc2 = (np.sum(a < thresh) + np.sum(b >= thresh)) / (len(a) + len(b))
        acc = max(acc1, acc2)
        if acc > best_acc:
            best_acc = acc
            best_thresh = thresh
    return float(best_acc), float(best_thresh)


def main():
    print("=" * 70)
    print("Fz NEUROFEEDBACK VALIDATION")
    print("3-condition test: meditation vs drowsy vs mental math")
    print("=" * 70)

    # Load recordings
    conditions = {}
    for label in ["meditation", "drowsy", "mental_math"]:
        try:
            files = find_fif_files(label)
            print(f"  {label}: {len(files)} files")
            conditions[label] = concat_fifs(files)
        except FileNotFoundError as e:
            print(f"  ERROR: {e}")
            return

    # Run ZUNA on all three conditions
    print("\n" + "=" * 70)
    print("RUNNING ZUNA SUPERRESOLUTION")
    print("=" * 70)

    zuna_conditions = {}
    for label, raw in conditions.items():
        print(f"\n  Processing {label}...")
        zuna_conditions[label] = run_zuna(raw, f"fz_{label}")
        print(f"  Output: {len(zuna_conditions[label].ch_names)} channels, "
              f"{zuna_conditions[label].times[-1]:.1f}s")

    # Part A: Window size degradation
    print("\n" + "=" * 70)
    print("PART A: WINDOW SIZE DEGRADATION CURVE")
    print("=" * 70)

    window_sizes = [60, 30, 10, 5, 2, 1]
    pairs = [("meditation", "drowsy"), ("meditation", "mental_math"), ("drowsy", "mental_math")]

    # Compute features for ZUNA data (has Fz) at each window size
    print("\n  Computing features from ZUNA 23ch data...")
    zuna_features: dict[str, dict[float, dict]] = {}
    for label, raw in zuna_conditions.items():
        sr = int(raw.info["sfreq"])
        data_uv = raw.get_data() * 1e6
        zuna_features[label] = {}
        for ws in window_sizes:
            zuna_features[label][ws] = window_features(data_uv, sr, list(raw.ch_names), ws)

    # Also compute AF alpha from ORIGINAL 4ch data
    print("  Computing features from original 4ch data...")
    orig_features: dict[str, dict[float, dict]] = {}
    for label, raw in conditions.items():
        sr = int(raw.info["sfreq"])
        data_uv = raw.get_data() * 1e6
        orig_features[label] = {}
        for ws in window_sizes:
            orig_features[label][ws] = window_features(data_uv, sr, list(raw.ch_names), ws)

    # Print degradation table for key metrics
    for metric_name, source, key in [
        ("Fz theta (ZUNA)", "zuna", "fz_theta"),
        ("Fz theta/beta (ZUNA)", "zuna", "fz_theta_beta"),
        ("AF7+AF8 alpha (raw 4ch)", "orig", "af_alpha"),
        ("AF7+AF8 theta/beta (raw 4ch)", "orig", "af_theta_beta"),
    ]:
        print(f"\n  {metric_name}:")
        feats = zuna_features if source == "zuna" else orig_features
        header = f"    {'Window':>8s}"
        for a, b in pairs:
            header += f" | {a[:3]}v{b[:3]:>6s}"
        print(header)
        print("    " + "-" * (10 + 15 * len(pairs)))

        for ws in window_sizes:
            row = f"    {ws:>6.0f}s "
            for a, b in pairs:
                va = np.array(feats[a][ws].get(key, []))
                vb = np.array(feats[b][ws].get(key, []))
                if len(va) >= 2 and len(vb) >= 2:
                    d = abs(cohens_d(va, vb))
                    row += f" |     {d:5.2f}"
                else:
                    row += f" |       n/a"
            print(row)

    # Part B: 3-condition discrimination matrix at 5s windows
    print("\n" + "=" * 70)
    print("PART B: 3-CONDITION DISCRIMINATION MATRIX (5s windows)")
    print("=" * 70)

    ws = 5
    metrics = [
        ("Fz theta (ZUNA)", "zuna", "fz_theta"),
        ("Fz theta/beta (ZUNA)", "zuna", "fz_theta_beta"),
        ("AF alpha (raw)", "orig", "af_alpha"),
        ("AF theta/beta (raw)", "orig", "af_theta_beta"),
        ("AF theta (raw)", "orig", "af_theta"),
    ]

    print(f"\n  {'Metric':30s} | {'med v drow':>10s} | {'med v math':>10s} | {'drow v math':>11s}")
    print("  " + "-" * 70)

    for name, source, key in metrics:
        feats = zuna_features if source == "zuna" else orig_features
        vals = {}
        for label in ["meditation", "drowsy", "mental_math"]:
            vals[label] = np.array(feats[label][ws].get(key, []))

        row = f"  {name:30s}"
        for a, b in pairs:
            if len(vals[a]) >= 2 and len(vals[b]) >= 2:
                d = cohens_d(vals[a], vals[b])
                row += f" |     {d:+5.2f}"
            else:
                row += f" |       n/a"
        print(row)

    # Print means for context
    print(f"\n  Means at 5s windows:")
    print(f"  {'Metric':30s} | {'meditation':>10s} | {'drowsy':>10s} | {'mental_math':>11s}")
    print("  " + "-" * 70)
    for name, source, key in metrics:
        feats = zuna_features if source == "zuna" else orig_features
        row = f"  {name:30s}"
        for label in ["meditation", "drowsy", "mental_math"]:
            v = np.array(feats[label][ws].get(key, []))
            if len(v) > 0:
                row += f" |   {np.mean(v):8.3f}"
            else:
                row += f" |       n/a"
        print(row)

    # Part C: Binary classification accuracy
    print("\n" + "=" * 70)
    print("PART C: CLASSIFICATION ACCURACY (2s and 5s windows)")
    print("=" * 70)

    for ws_c in [5, 2]:
        print(f"\n  Window size: {ws_c}s")
        print(f"  {'Metric':30s} | {'med v drow':>10s} | {'med v math':>10s} | {'drow v math':>11s}")
        print("  " + "-" * 70)

        for name, source, key in metrics:
            feats = zuna_features if source == "zuna" else orig_features
            row = f"  {name:30s}"
            for a, b in pairs:
                va = np.array(feats[a][ws_c].get(key, []))
                vb = np.array(feats[b][ws_c].get(key, []))
                if len(va) >= 2 and len(vb) >= 2:
                    acc, _ = classification_accuracy(va, vb)
                    row += f" |     {acc:5.1%}"
                else:
                    row += f" |       n/a"
            print(row)

    # Verdict
    print("\n" + "=" * 70)
    print("VERDICT")
    print("=" * 70)

    # Key test: meditation vs drowsy at 5s
    fz_med = np.array(zuna_features["meditation"][5].get("fz_theta", []))
    fz_dro = np.array(zuna_features["drowsy"][5].get("fz_theta", []))
    af_med = np.array(orig_features["meditation"][5].get("af_alpha", []))
    af_dro = np.array(orig_features["drowsy"][5].get("af_alpha", []))

    if len(fz_med) >= 2 and len(fz_dro) >= 2:
        d_fz = abs(cohens_d(fz_med, fz_dro))
        d_af = abs(cohens_d(af_med, af_dro))

        print(f"\n  KEY TEST: meditation vs drowsy at 5s windows")
        print(f"    Fz theta (ZUNA):    d = {d_fz:.2f}  (mean: med={np.mean(fz_med):.2f}, drow={np.mean(fz_dro):.2f})")
        print(f"    AF alpha (raw 4ch): d = {d_af:.2f}  (mean: med={np.mean(af_med):.2f}, drow={np.mean(af_dro):.2f})")

        if d_fz > 0.8 and d_af < 0.3:
            print(f"\n  EXCELLENT: Fz theta separates meditation from drowsy (d={d_fz:.2f})")
            print(f"  while AF alpha cannot (d={d_af:.2f}). ZUNA enables unique neurofeedback.")
        elif d_fz > 0.5 and d_af < 0.3:
            print(f"\n  GOOD: Fz theta shows moderate separation (d={d_fz:.2f})")
            print(f"  while AF alpha fails (d={d_af:.2f}). ZUNA adds value but signal is weak.")
        elif d_fz > 0.5 and d_af > 0.5:
            print(f"\n  INCONCLUSIVE: Both Fz theta (d={d_fz:.2f}) and AF alpha (d={d_af:.2f})")
            print(f"  separate the conditions. Cannot prove ZUNA's unique value.")
        else:
            print(f"\n  FAILED: Fz theta does not separate meditation from drowsy (d={d_fz:.2f}).")
            print(f"  ZUNA virtual Fz does not provide neurofeedback-quality FMθ from Muse.")

    # 2s check
    fz_med_2 = np.array(zuna_features["meditation"][2].get("fz_theta", []))
    fz_dro_2 = np.array(zuna_features["drowsy"][2].get("fz_theta", []))
    if len(fz_med_2) >= 2 and len(fz_dro_2) >= 2:
        d_fz_2 = abs(cohens_d(fz_med_2, fz_dro_2))
        print(f"\n  At 2s windows: Fz theta d = {d_fz_2:.2f}")
        if d_fz_2 > 0.8:
            print(f"  -> Viable for responsive neurofeedback (2s update rate)")
        elif d_fz_2 > 0.5:
            print(f"  -> Marginal at 2s. May need 5s windows for reliable feedback.")
        else:
            print(f"  -> Too weak at 2s. Minimum 5s windows needed.")


if __name__ == "__main__":
    main()
