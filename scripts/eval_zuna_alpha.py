#!/usr/bin/env python3
"""Evaluate ZUNA superresolution for BCI: alpha blocking experiment.

Compares eyes-closed vs eyes-open recordings on:
  1. Original 4 channels (TP9, AF7, AF8, TP10)
  2. ZUNA-reconstructed 23 channels (including virtual O1, O2, Pz, etc.)

If ZUNA produces meaningful virtual channels, occipital alpha should be
significantly higher in eyes-closed vs eyes-open.

Usage:
    PYTHONPATH=. python scripts/eval_zuna_alpha.py

Expects recordings in:
    recordings/eyes_closed/<session>/*_raw.fif
    recordings/eyes_open/<session>/*_raw.fif
"""
import shutil
import time
from pathlib import Path

import mne
import numpy as np
from scipy.signal import welch

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
OCCIPITAL = ["O1", "O2"]
PARIETAL = ["P3", "Pz", "P4"]
FRONTAL_VIRTUAL = ["Fp1", "Fp2", "F3", "Fz", "F4"]
CENTRAL = ["C3", "Cz", "C4"]


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
    print(f"  Concatenated {len(files)} files → {combined.times[-1]:.1f}s")
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


def analyze_condition(raw: mne.io.Raw, label: str, channel_groups: dict[str, list[str]]):
    """Compute band powers per channel group."""
    data_uv = raw.get_data() * 1e6
    sr = int(raw.info["sfreq"])
    results = {}

    for group_name, channels in channel_groups.items():
        available = [ch for ch in channels if ch in raw.ch_names]
        if not available:
            continue
        group_alpha = []
        group_beta = []
        group_theta = []
        for ch in available:
            idx = raw.ch_names.index(ch)
            alpha = band_power(data_uv[idx], sr, 8, 13)
            beta = band_power(data_uv[idx], sr, 13, 30)
            theta = band_power(data_uv[idx], sr, 4, 8)
            group_alpha.append(alpha)
            group_beta.append(beta)
            group_theta.append(theta)
        results[group_name] = {
            "alpha": np.mean(group_alpha),
            "beta": np.mean(group_beta),
            "theta": np.mean(group_theta),
            "alpha_beta_ratio": np.mean(group_alpha) / max(np.mean(group_beta), 0.01),
            "channels": available,
        }

    return results


def main():
    print("=" * 70)
    print("ZUNA ALPHA BLOCKING EXPERIMENT")
    print("=" * 70)

    # Find recordings
    try:
        ec_files = find_fif_files("eyes_closed")
        eo_files = find_fif_files("eyes_open")
    except FileNotFoundError as e:
        print(f"\nERROR: {e}")
        print("Record eyes_closed and eyes_open protocols first.")
        return

    print(f"\nEyes closed: {len(ec_files)} files")
    print(f"Eyes open:   {len(eo_files)} files")

    # Concatenate
    print("\n--- Concatenating recordings ---")
    ec_raw = concat_fifs(ec_files)
    eo_raw = concat_fifs(eo_files)

    # Channel groups for analysis
    groups_4ch = {
        "frontal (AF7+AF8)": ["AF7", "AF8"],
        "temporal (TP9+TP10)": ["TP9", "TP10"],
    }

    groups_23ch = {
        "frontal_orig (AF7+AF8)": ["AF7", "AF8"],
        "temporal_orig (TP9+TP10)": ["TP9", "TP10"],
        "occipital (O1+O2)": ["O1", "O2"],
        "parietal (P3+Pz+P4)": ["P3", "Pz", "P4"],
        "central (C3+Cz+C4)": ["C3", "Cz", "C4"],
        "frontal_virtual (Fp1+Fp2+F3+Fz+F4)": ["Fp1", "Fp2", "F3", "Fz", "F4"],
    }

    # --- Analysis on ORIGINAL 4ch ---
    print("\n" + "=" * 70)
    print("ORIGINAL 4 CHANNELS")
    print("=" * 70)

    ec_orig = analyze_condition(ec_raw, "eyes_closed", groups_4ch)
    eo_orig = analyze_condition(eo_raw, "eyes_open", groups_4ch)

    print(f"\n{'Group':35s} | {'EC alpha':>10s} | {'EO alpha':>10s} | {'EC/EO':>7s} | {'Verdict':>10s}")
    print("-" * 80)
    for group in groups_4ch:
        ec_a = ec_orig[group]["alpha"]
        eo_a = eo_orig[group]["alpha"]
        ratio = ec_a / max(eo_a, 0.01)
        verdict = "GOOD" if ratio > 1.5 else "WEAK" if ratio > 1.1 else "NONE"
        print(f"  {group:33s} | {ec_a:10.1f} | {eo_a:10.1f} | {ratio:7.2f} | {verdict:>10s}")

    # --- Run ZUNA ---
    print("\n" + "=" * 70)
    print("RUNNING ZUNA SUPERRESOLUTION")
    print("=" * 70)

    print("\nProcessing eyes_closed...")
    ec_zuna = run_zuna(ec_raw, "eyes_closed")
    print(f"  Output: {len(ec_zuna.ch_names)} channels, {ec_zuna.times[-1]:.1f}s")

    print("\nProcessing eyes_open...")
    eo_zuna = run_zuna(eo_raw, "eyes_open")
    print(f"  Output: {len(eo_zuna.ch_names)} channels, {eo_zuna.times[-1]:.1f}s")

    # --- Analysis on ZUNA 23ch ---
    print("\n" + "=" * 70)
    print("ZUNA RECONSTRUCTED 23 CHANNELS")
    print("=" * 70)

    ec_recon = analyze_condition(ec_zuna, "eyes_closed", groups_23ch)
    eo_recon = analyze_condition(eo_zuna, "eyes_open", groups_23ch)

    print(f"\n{'Group':35s} | {'EC alpha':>10s} | {'EO alpha':>10s} | {'EC/EO':>7s} | {'Verdict':>10s}")
    print("-" * 80)
    for group in groups_23ch:
        if group not in ec_recon or group not in eo_recon:
            continue
        ec_a = ec_recon[group]["alpha"]
        eo_a = eo_recon[group]["alpha"]
        ratio = ec_a / max(eo_a, 0.01)
        verdict = "GOOD" if ratio > 1.5 else "WEAK" if ratio > 1.1 else "NONE"
        print(f"  {group:33s} | {ec_a:10.1f} | {eo_a:10.1f} | {ratio:7.2f} | {verdict:>10s}")

    # --- Summary ---
    print("\n" + "=" * 70)
    print("EXPERIMENT SUMMARY")
    print("=" * 70)

    # Key question: does occipital alpha from ZUNA discriminate EC vs EO?
    if "occipital (O1+O2)" in ec_recon and "occipital (O1+O2)" in eo_recon:
        occ_ec = ec_recon["occipital (O1+O2)"]["alpha"]
        occ_eo = eo_recon["occipital (O1+O2)"]["alpha"]
        occ_ratio = occ_ec / max(occ_eo, 0.01)
        print(f"\n  Occipital alpha (ZUNA virtual O1+O2):")
        print(f"    Eyes closed: {occ_ec:.1f} µV²")
        print(f"    Eyes open:   {occ_eo:.1f} µV²")
        print(f"    Ratio:       {occ_ratio:.2f}x")
        if occ_ratio > 2.0:
            print(f"    → STRONG alpha blocking at virtual occipital channels")
            print(f"    → ZUNA produces spatially meaningful virtual channels")
        elif occ_ratio > 1.3:
            print(f"    → WEAK alpha blocking — some spatial info but noisy")
        else:
            print(f"    → NO alpha blocking — virtual channels are hallucinated")

    # Compare discrimination power: original 4ch vs ZUNA 23ch
    if "frontal (AF7+AF8)" in ec_orig:
        orig_ratio = ec_orig["frontal (AF7+AF8)"]["alpha"] / max(eo_orig["frontal (AF7+AF8)"]["alpha"], 0.01)
        print(f"\n  Original frontal alpha EC/EO ratio: {orig_ratio:.2f}x")

    if "frontal_orig (AF7+AF8)" in ec_recon:
        recon_ratio = ec_recon["frontal_orig (AF7+AF8)"]["alpha"] / max(eo_recon["frontal_orig (AF7+AF8)"]["alpha"], 0.01)
        print(f"  ZUNA frontal alpha EC/EO ratio:     {recon_ratio:.2f}x")

    print("\n  Conclusion: ", end="")
    if "occipital (O1+O2)" in ec_recon:
        if occ_ratio > 1.5:
            print("ZUNA adds useful spatial information for alpha-based BCI")
        else:
            print("ZUNA does NOT add useful spatial information from 4 Muse channels")


if __name__ == "__main__":
    main()
