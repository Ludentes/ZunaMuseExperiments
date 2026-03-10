#!/usr/bin/env python3
"""Evaluate meditation vs mental math engagement using EEG band powers.

Compares meditation vs mental_math recordings on:
  1. Original 4 channels (TP9, AF7, AF8, TP10)
  2. ZUNA-reconstructed 23 channels (virtual occipital, parietal, central, frontal)
  3. BrainFlow MLModel(MINDFULNESS) classifier on both raw and ZUNA-denoised data

Key metrics: theta/beta ratio, alpha power, frontal asymmetry, band separations.

Usage:
    PYTHONPATH=. python scripts/eval_engagement.py
"""
import shutil
import time
from pathlib import Path

import mne
import numpy as np
from brainflow import DataFilter, MLModel, BrainFlowModelParams, BrainFlowMetrics, BrainFlowClassifiers
from scipy.signal import welch

mne.set_log_level("WARNING")
DataFilter.set_log_level(3)

CHANNELS_TO_ADD_19 = [
    "Fp1", "Fp2", "F7", "F3", "Fz", "F4", "F8",
    "T3", "C3", "Cz", "C4", "T4",
    "T5", "P3", "Pz", "P4", "T6",
    "O1", "O2",
]

BANDS = {
    "delta": (1, 4),
    "theta": (4, 8),
    "alpha": (8, 13),
    "beta": (13, 30),
    "gamma": (30, 50),
}

MUSE_CH = ["TP9", "AF7", "AF8", "TP10"]


# =============================================================================
# Helper functions (same style as eval_zuna_alpha.py)
# =============================================================================

def band_power(data_uv: np.ndarray, sr: int, lo: float, hi: float) -> float:
    """Compute band power in uV^2 using Welch's method."""
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


# =============================================================================
# Analysis functions
# =============================================================================

def compute_all_band_powers(raw: mne.io.Raw, channels: list[str]) -> dict:
    """Compute all band powers per channel. Returns {ch: {band: power_uV2}}."""
    data_uv = raw.get_data() * 1e6
    sr = int(raw.info["sfreq"])
    results = {}
    for ch in channels:
        if ch not in raw.ch_names:
            continue
        idx = raw.ch_names.index(ch)
        results[ch] = {}
        for band_name, (lo, hi) in BANDS.items():
            results[ch][band_name] = band_power(data_uv[idx], sr, lo, hi)
    return results


def compute_group_metrics(raw: mne.io.Raw, channel_groups: dict[str, list[str]]) -> dict:
    """Compute band powers and derived metrics per channel group."""
    data_uv = raw.get_data() * 1e6
    sr = int(raw.info["sfreq"])
    results = {}

    for group_name, channels in channel_groups.items():
        available = [ch for ch in channels if ch in raw.ch_names]
        if not available:
            continue

        group_bands = {b: [] for b in BANDS}
        for ch in available:
            idx = raw.ch_names.index(ch)
            for band_name, (lo, hi) in BANDS.items():
                group_bands[band_name].append(band_power(data_uv[idx], sr, lo, hi))

        mean_bands = {b: np.mean(vals) for b, vals in group_bands.items()}
        theta_beta = mean_bands["theta"] / max(mean_bands["beta"], 0.01)
        alpha_beta = mean_bands["alpha"] / max(mean_bands["beta"], 0.01)

        results[group_name] = {
            **mean_bands,
            "theta_beta_ratio": theta_beta,
            "alpha_beta_ratio": alpha_beta,
            "channels": available,
        }

    return results


def compute_frontal_asymmetry(raw: mne.io.Raw) -> float | None:
    """Compute frontal alpha asymmetry: ln(AF8_alpha) - ln(AF7_alpha).
    Positive = greater left-frontal activity (approach motivation)."""
    data_uv = raw.get_data() * 1e6
    sr = int(raw.info["sfreq"])

    if "AF7" not in raw.ch_names or "AF8" not in raw.ch_names:
        return None

    af7_idx = raw.ch_names.index("AF7")
    af8_idx = raw.ch_names.index("AF8")
    af7_alpha = band_power(data_uv[af7_idx], sr, 8, 13)
    af8_alpha = band_power(data_uv[af8_idx], sr, 8, 13)

    if af7_alpha <= 0 or af8_alpha <= 0:
        return None
    return float(np.log(af8_alpha) - np.log(af7_alpha))


def compute_mindfulness_scores(raw: mne.io.Raw, label: str) -> list[float]:
    """Compute BrainFlow MINDFULNESS scores using 2s windows, 1s stride.
    Returns list of scores."""
    data = raw.get_data() * 1e6  # to uV for BrainFlow
    sr = int(raw.info["sfreq"])
    n_samples = data.shape[1]
    win_samples = int(2 * sr)
    stride_samples = int(1 * sr)

    # Use first 4 EEG channels (indices 0-3)
    n_ch = min(4, data.shape[0])
    eeg_channels = list(range(n_ch))

    params = BrainFlowModelParams(
        BrainFlowMetrics.MINDFULNESS.value,
        BrainFlowClassifiers.DEFAULT_CLASSIFIER.value,
    )
    model = MLModel(params)
    model.prepare()

    scores = []
    pos = 0
    while pos + win_samples <= n_samples:
        window = np.ascontiguousarray(data[:n_ch, pos:pos + win_samples])
        try:
            bands = DataFilter.get_avg_band_powers(window, eeg_channels, sr, True)
            score = model.predict(np.array(bands[0]))
            scores.append(float(score))
        except Exception:
            pass  # skip windows that fail
        pos += stride_samples

    model.release()
    return scores


def separation(vals_a: list[float] | np.ndarray, vals_b: list[float] | np.ndarray) -> float:
    """Cohen's d style separation: |mean_a - mean_b| / pooled_std."""
    a = np.array(vals_a, dtype=float)
    b = np.array(vals_b, dtype=float)
    if len(a) == 0 or len(b) == 0:
        return 0.0
    mean_diff = abs(np.mean(a) - np.mean(b))
    pooled_var = (np.var(a, ddof=1) * (len(a) - 1) + np.var(b, ddof=1) * (len(b) - 1)) / (len(a) + len(b) - 2)
    pooled_std = np.sqrt(pooled_var) if pooled_var > 0 else 1e-9
    return float(mean_diff / pooled_std)


def scalar_separation(mean_a: float, mean_b: float, std_a: float, std_b: float) -> float:
    """Separation from group-level means and stds."""
    pooled_std = np.sqrt((std_a**2 + std_b**2) / 2) if (std_a + std_b) > 0 else 1e-9
    return abs(mean_a - mean_b) / pooled_std


# =============================================================================
# Printing helpers
# =============================================================================

def print_section(title: str):
    print(f"\n{'=' * 70}")
    print(title)
    print("=" * 70)


def print_band_table(med_bp: dict, math_bp: dict, channels: list[str]):
    """Print per-channel band powers for both conditions."""
    header = f"  {'Channel':8s}"
    for b in BANDS:
        header += f" | {b:>8s}"
    header += " | {'t/b':>6s}"
    print(f"  {'Channel':8s}", end="")
    for b in BANDS:
        print(f" | {b:>8s}", end="")
    print(f" | {'t/b':>6s}")
    print("  " + "-" * 72)

    for ch in channels:
        if ch not in med_bp or ch not in math_bp:
            continue
        # Meditation
        print(f"  {ch + ' med':8s}", end="")
        for b in BANDS:
            print(f" | {med_bp[ch][b]:8.1f}", end="")
        tb = med_bp[ch]["theta"] / max(med_bp[ch]["beta"], 0.01)
        print(f" | {tb:6.2f}")
        # Math
        print(f"  {ch + ' math':8s}", end="")
        for b in BANDS:
            print(f" | {math_bp[ch][b]:8.1f}", end="")
        tb = math_bp[ch]["theta"] / max(math_bp[ch]["beta"], 0.01)
        print(f" | {tb:6.2f}")


def print_group_comparison(med_groups: dict, math_groups: dict, group_names: list[str]):
    """Print group metrics comparison table."""
    print(f"\n  {'Group':30s} | {'Med t/b':>8s} | {'Math t/b':>8s} | {'Med a/b':>8s} | {'Math a/b':>8s} | {'Med alpha':>10s} | {'Math alpha':>10s}")
    print("  " + "-" * 100)
    for g in group_names:
        if g not in med_groups or g not in math_groups:
            continue
        m = med_groups[g]
        x = math_groups[g]
        print(f"  {g:30s} | {m['theta_beta_ratio']:8.2f} | {x['theta_beta_ratio']:8.2f} | {m['alpha_beta_ratio']:8.2f} | {x['alpha_beta_ratio']:8.2f} | {m['alpha']:10.1f} | {x['alpha']:10.1f}")


# =============================================================================
# Main
# =============================================================================

def main():
    print_section("ENGAGEMENT ANALYSIS: MEDITATION vs MENTAL MATH")

    # --- Load recordings ---
    try:
        med_files = find_fif_files("meditation")
        math_files = find_fif_files("mental_math")
    except FileNotFoundError as e:
        print(f"\nERROR: {e}")
        print("Record meditation and mental_math protocols first.")
        return

    print(f"\nMeditation:  {len(med_files)} files")
    print(f"Mental math: {len(math_files)} files")

    print("\n--- Concatenating recordings ---")
    med_raw = concat_fifs(med_files)
    math_raw = concat_fifs(math_files)

    # =========================================================================
    # SECTION 1: Original 4 channels
    # =========================================================================
    print_section("ORIGINAL 4 CHANNELS — PER-CHANNEL BAND POWERS")

    med_bp = compute_all_band_powers(med_raw, MUSE_CH)
    math_bp = compute_all_band_powers(math_raw, MUSE_CH)
    print_band_table(med_bp, math_bp, MUSE_CH)

    # Group metrics on 4ch
    groups_4ch = {
        "frontal_orig": ["AF7", "AF8"],
        "temporal_orig": ["TP9", "TP10"],
    }

    med_g4 = compute_group_metrics(med_raw, groups_4ch)
    math_g4 = compute_group_metrics(math_raw, groups_4ch)
    print_group_comparison(med_g4, math_g4, list(groups_4ch.keys()))

    # Frontal asymmetry
    med_asym = compute_frontal_asymmetry(med_raw)
    math_asym = compute_frontal_asymmetry(math_raw)
    print(f"\n  Frontal alpha asymmetry (ln AF8 - ln AF7):")
    print(f"    Meditation:  {med_asym:+.3f}" if med_asym is not None else "    Meditation:  N/A")
    print(f"    Mental math: {math_asym:+.3f}" if math_asym is not None else "    Mental math: N/A")

    # =========================================================================
    # SECTION 2: BrainFlow MINDFULNESS on raw 4ch
    # =========================================================================
    print_section("BRAINFLOW MINDFULNESS CLASSIFIER — RAW 4ch")

    print("  Computing mindfulness scores (2s windows, 1s stride)...")
    med_mf_raw = compute_mindfulness_scores(med_raw, "meditation_raw")
    math_mf_raw = compute_mindfulness_scores(math_raw, "math_raw")

    if med_mf_raw and math_mf_raw:
        med_mf_arr = np.array(med_mf_raw)
        math_mf_arr = np.array(math_mf_raw)
        sep_mf_raw = separation(med_mf_arr, math_mf_arr)
        print(f"    Meditation:  mean={np.mean(med_mf_arr):.3f}  std={np.std(med_mf_arr):.3f}  n={len(med_mf_arr)}")
        print(f"    Mental math: mean={np.mean(math_mf_arr):.3f}  std={np.std(math_mf_arr):.3f}  n={len(math_mf_arr)}")
        print(f"    Separation (Cohen's d): {sep_mf_raw:.2f}")
    else:
        sep_mf_raw = 0.0
        print("    Failed to compute scores.")

    # =========================================================================
    # SECTION 3: Run ZUNA
    # =========================================================================
    print_section("RUNNING ZUNA SUPERRESOLUTION (4ch -> 23ch)")

    print("\nProcessing meditation...")
    med_zuna = run_zuna(med_raw, "meditation")
    print(f"  Output: {len(med_zuna.ch_names)} channels, {med_zuna.times[-1]:.1f}s")

    print("\nProcessing mental_math...")
    math_zuna = run_zuna(math_raw, "mental_math")
    print(f"  Output: {len(math_zuna.ch_names)} channels, {math_zuna.times[-1]:.1f}s")

    # =========================================================================
    # SECTION 4: ZUNA 23ch analysis
    # =========================================================================
    print_section("ZUNA 23 CHANNELS — GROUP METRICS")

    groups_23ch = {
        "frontal_orig": ["AF7", "AF8"],
        "temporal_orig": ["TP9", "TP10"],
        "occipital": ["O1", "O2"],
        "parietal": ["P3", "Pz", "P4"],
        "central": ["C3", "Cz", "C4"],
        "frontal_virtual": ["Fp1", "Fp2", "F3", "Fz", "F4"],
        "frontal_midline": ["Fz"],
    }

    med_g23 = compute_group_metrics(med_zuna, groups_23ch)
    math_g23 = compute_group_metrics(math_zuna, groups_23ch)
    print_group_comparison(med_g23, math_g23, list(groups_23ch.keys()))

    # =========================================================================
    # SECTION 5: BrainFlow MINDFULNESS on ZUNA-denoised 4ch
    # =========================================================================
    print_section("BRAINFLOW MINDFULNESS CLASSIFIER — ZUNA DENOISED 4ch")

    # Extract original 4 channels from ZUNA output
    med_zuna_4ch = med_zuna.copy().pick_channels([ch for ch in MUSE_CH if ch in med_zuna.ch_names])
    math_zuna_4ch = math_zuna.copy().pick_channels([ch for ch in MUSE_CH if ch in math_zuna.ch_names])

    print("  Computing mindfulness scores (2s windows, 1s stride)...")
    med_mf_zuna = compute_mindfulness_scores(med_zuna_4ch, "meditation_zuna")
    math_mf_zuna = compute_mindfulness_scores(math_zuna_4ch, "math_zuna")

    if med_mf_zuna and math_mf_zuna:
        med_mf_z_arr = np.array(med_mf_zuna)
        math_mf_z_arr = np.array(math_mf_zuna)
        sep_mf_zuna = separation(med_mf_z_arr, math_mf_z_arr)
        print(f"    Meditation:  mean={np.mean(med_mf_z_arr):.3f}  std={np.std(med_mf_z_arr):.3f}  n={len(med_mf_z_arr)}")
        print(f"    Mental math: mean={np.mean(math_mf_z_arr):.3f}  std={np.std(math_mf_z_arr):.3f}  n={len(math_mf_z_arr)}")
        print(f"    Separation (Cohen's d): {sep_mf_zuna:.2f}")
    else:
        sep_mf_zuna = 0.0
        print("    Failed to compute scores.")

    # =========================================================================
    # SECTION 6: Separation metrics summary
    # =========================================================================
    print_section("SEPARATION METRICS SUMMARY")

    print(f"\n  {'Metric':45s} | {'Med mean':>10s} | {'Math mean':>10s} | {'Sep (d)':>8s} | {'Verdict':>8s}")
    print("  " + "-" * 90)

    all_separations = []

    # 4ch group separations
    for g in groups_4ch:
        if g in med_g4 and g in math_g4:
            for metric in ["theta_beta_ratio", "alpha_beta_ratio", "alpha", "beta", "theta"]:
                m_val = med_g4[g][metric]
                x_val = math_g4[g][metric]
                # Use simple separation with assumed 30% CV
                std_est = 0.3 * (abs(m_val) + abs(x_val)) / 2
                d = abs(m_val - x_val) / max(std_est, 1e-9)
                verdict = "GOOD" if d > 0.8 else "WEAK" if d > 0.3 else "NONE"
                label = f"4ch {g} {metric}"
                print(f"  {label:45s} | {m_val:10.3f} | {x_val:10.3f} | {d:8.2f} | {verdict:>8s}")
                all_separations.append((label, d))

    # 23ch group separations
    for g in groups_23ch:
        if g in med_g23 and g in math_g23:
            for metric in ["theta_beta_ratio", "alpha_beta_ratio", "alpha", "beta", "theta"]:
                m_val = med_g23[g][metric]
                x_val = math_g23[g][metric]
                std_est = 0.3 * (abs(m_val) + abs(x_val)) / 2
                d = abs(m_val - x_val) / max(std_est, 1e-9)
                verdict = "GOOD" if d > 0.8 else "WEAK" if d > 0.3 else "NONE"
                label = f"23ch {g} {metric}"
                print(f"  {label:45s} | {m_val:10.3f} | {x_val:10.3f} | {d:8.2f} | {verdict:>8s}")
                all_separations.append((label, d))

    # Frontal asymmetry
    if med_asym is not None and math_asym is not None:
        asym_diff = abs(med_asym - math_asym)
        std_est = 0.3 * (abs(med_asym) + abs(math_asym)) / 2
        d = asym_diff / max(std_est, 1e-9)
        verdict = "GOOD" if d > 0.8 else "WEAK" if d > 0.3 else "NONE"
        label = "4ch frontal_asymmetry"
        print(f"  {label:45s} | {med_asym:10.3f} | {math_asym:10.3f} | {d:8.2f} | {verdict:>8s}")
        all_separations.append((label, d))

    # Mindfulness scores
    if med_mf_raw and math_mf_raw:
        label = "BrainFlow mindfulness (raw 4ch)"
        print(f"  {label:45s} | {np.mean(med_mf_raw):10.3f} | {np.mean(math_mf_raw):10.3f} | {sep_mf_raw:8.2f} | {'GOOD' if sep_mf_raw > 0.8 else 'WEAK' if sep_mf_raw > 0.3 else 'NONE':>8s}")
        all_separations.append((label, sep_mf_raw))

    if med_mf_zuna and math_mf_zuna:
        label = "BrainFlow mindfulness (ZUNA 4ch)"
        print(f"  {label:45s} | {np.mean(med_mf_zuna):10.3f} | {np.mean(math_mf_zuna):10.3f} | {sep_mf_zuna:8.2f} | {'GOOD' if sep_mf_zuna > 0.8 else 'WEAK' if sep_mf_zuna > 0.3 else 'NONE':>8s}")
        all_separations.append((label, sep_mf_zuna))

    # =========================================================================
    # SECTION 7: Viability assessment
    # =========================================================================
    print_section("VIABILITY ASSESSMENT")

    # Sort by separation
    all_separations.sort(key=lambda x: x[1], reverse=True)
    good_count = sum(1 for _, d in all_separations if d > 0.8)
    weak_count = sum(1 for _, d in all_separations if 0.3 < d <= 0.8)
    none_count = sum(1 for _, d in all_separations if d <= 0.3)

    print(f"\n  Total metrics evaluated: {len(all_separations)}")
    print(f"  GOOD (d > 0.8): {good_count}")
    print(f"  WEAK (0.3 < d <= 0.8): {weak_count}")
    print(f"  NONE (d <= 0.3): {none_count}")

    if all_separations:
        print(f"\n  Top 5 discriminating features:")
        for i, (label, d) in enumerate(all_separations[:5]):
            print(f"    {i+1}. {label}: d={d:.2f}")

    # Key checks
    print(f"\n  Key findings:")

    # Check theta/beta ratio (classic engagement)
    tb_seps = [(l, d) for l, d in all_separations if "theta_beta" in l]
    if tb_seps:
        best_tb = max(tb_seps, key=lambda x: x[1])
        print(f"    - Best theta/beta separation: {best_tb[0]} (d={best_tb[1]:.2f})")

    # Check mindfulness classifier
    mf_seps = [(l, d) for l, d in all_separations if "mindfulness" in l]
    if mf_seps:
        best_mf = max(mf_seps, key=lambda x: x[1])
        print(f"    - Best mindfulness classifier: {best_mf[0]} (d={best_mf[1]:.2f})")

    # Check if ZUNA helps
    zuna_seps = [d for l, d in all_separations if "23ch" in l]
    orig_seps = [d for l, d in all_separations if "4ch" in l and "23ch" not in l]
    if zuna_seps and orig_seps:
        zuna_avg = np.mean(zuna_seps)
        orig_avg = np.mean(orig_seps)
        print(f"    - Average separation: 4ch={orig_avg:.2f}, ZUNA 23ch={zuna_avg:.2f}")
        if zuna_avg > orig_avg * 1.2:
            print(f"    - ZUNA IMPROVES separation by {(zuna_avg/orig_avg - 1)*100:.0f}%")
        elif zuna_avg < orig_avg * 0.8:
            print(f"    - ZUNA HURTS separation by {(1 - zuna_avg/orig_avg)*100:.0f}%")
        else:
            print(f"    - ZUNA has SIMILAR separation to raw 4ch")

    # Overall verdict
    print(f"\n  VERDICT: ", end="")
    if good_count >= 3:
        print("VIABLE for demo. Multiple features show strong separation.")
        print("  Recommendation: Use top features as engagement index.")
    elif good_count >= 1 or weak_count >= 3:
        print("MARGINAL. Some separation exists but may not be robust.")
        print("  Recommendation: Combine multiple weak features or use longer windows.")
    else:
        print("NOT VIABLE. Meditation vs mental math not separable with current setup.")
        print("  Recommendation: Try different tasks or longer recording sessions.")


if __name__ == "__main__":
    main()
