#!/usr/bin/env python3
"""Evaluate SSVEP detection on Muse 2 with and without ZUNA superresolution.

SSVEP (Steady-State Visual Evoked Potentials): flickering visual stimulus at
frequency F produces a spectral peak at F in occipital EEG. The key question:
can ZUNA's virtual O1/O2 detect SSVEP that raw Muse channels cannot?

Conditions:
  ssvep_none  — static checkerboard (control)
  ssvep_6hz   — 6.0 Hz flicker
  ssvep_7hz   — 7.5 Hz flicker
  ssvep_10hz  — 10.0 Hz flicker
  ssvep_15hz  — 15.0 Hz flicker

Usage:
    PYTHONPATH=. python scripts/eval_ssvep.py
"""
import shutil
import time
from pathlib import Path

import mne
import numpy as np
from scipy import stats
from scipy.signal import welch

mne.set_log_level("WARNING")

try:
    from brainflow.data_filter import DataFilter
    DataFilter.set_log_level(3)
except Exception:
    pass

CHANNELS_TO_ADD_19 = [
    "Fp1", "Fp2", "F7", "F3", "Fz", "F4", "F8",
    "T3", "C3", "Cz", "C4", "T4",
    "T5", "P3", "Pz", "P4", "T6",
    "O1", "O2",
]

CONDITIONS = {
    "ssvep_none": 0.0,
    "ssvep_6hz": 6.0,
    "ssvep_7hz": 7.5,
    "ssvep_10hz": 10.0,
    "ssvep_15hz": 15.0,
}

TRIAL_DURATION = 15.0  # seconds per trial

GROUPS_4CH = {
    "frontal (AF7+AF8)": ["AF7", "AF8"],
    "temporal (TP9+TP10)": ["TP9", "TP10"],
}

GROUPS_23CH = {
    "occipital (O1+O2)": ["O1", "O2"],
    "temporal (TP9+TP10)": ["TP9", "TP10"],
    "frontal (AF7+AF8)": ["AF7", "AF8"],
    "parietal (P3+Pz+P4)": ["P3", "Pz", "P4"],
    "central (C3+Cz+C4)": ["C3", "Cz", "C4"],
}

# SNR detection thresholds to report
SNR_THRESHOLDS = [1.5, 2.0, 3.0]


# ── Helpers ──────────────────────────────────────────────────────────────────


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


def compute_psd(data_uv: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """Compute PSD using Welch's method. Returns (freqs, psd)."""
    nperseg = min(1024, len(data_uv))
    freqs, psd = welch(data_uv, fs=sr, nperseg=nperseg)
    return freqs, psd


def band_power(freqs: np.ndarray, psd: np.ndarray, lo: float, hi: float) -> float:
    """Compute power in a frequency band from precomputed PSD."""
    idx = (freqs >= lo) & (freqs <= hi)
    if not np.any(idx):
        return 0.0
    return float(np.trapezoid(psd[idx], freqs[idx]))


def compute_snr(freqs: np.ndarray, psd: np.ndarray, target_freq: float) -> float:
    """Compute SNR at target frequency.

    Signal band: target +/- 0.5 Hz
    Noise bands: (target-3 to target-1.5) and (target+1.5 to target+3)
    SNR = signal_power / mean(noise_power)
    """
    sig_power = band_power(freqs, psd, target_freq - 0.5, target_freq + 0.5)
    noise_lo = band_power(freqs, psd, target_freq - 3.0, target_freq - 1.5)
    noise_hi = band_power(freqs, psd, target_freq + 1.5, target_freq + 3.0)
    noise_mean = (noise_lo + noise_hi) / 2.0
    if noise_mean < 1e-12:
        return 0.0
    return sig_power / noise_mean


def snr_per_trial_group(
    raw: mne.io.Raw,
    channels: list[str],
    target_freq: float,
    trial_duration: float,
) -> list[float]:
    """Compute SNR at target_freq for each trial-length segment, averaged across channels."""
    available = [ch for ch in channels if ch in raw.ch_names]
    if not available:
        return []

    sr = int(raw.info["sfreq"])
    samples_per_trial = int(trial_duration * sr)
    data_uv = raw.get_data(picks=available) * 1e6  # (n_ch, n_samples)
    total_samples = data_uv.shape[1]
    n_trials = total_samples // samples_per_trial

    trial_snrs = []
    for t in range(n_trials):
        start = t * samples_per_trial
        end = start + samples_per_trial
        ch_snrs = []
        for ch_idx in range(len(available)):
            segment = data_uv[ch_idx, start:end]
            freqs, psd = compute_psd(segment, sr)
            ch_snrs.append(compute_snr(freqs, psd, target_freq))
        trial_snrs.append(float(np.mean(ch_snrs)))

    return trial_snrs


# ── Analysis ─────────────────────────────────────────────────────────────────


def analyze_raw_4ch(condition_files: dict[str, list[Path]]):
    """Analyze SSVEP on original 4 channels, per trial."""
    print("\n" + "=" * 70)
    print("ORIGINAL 4 CHANNELS — PER-TRIAL SSVEP ANALYSIS")
    print("=" * 70)

    # {condition: {group_name: [snr_per_trial]}}
    results: dict[str, dict[str, list[float]]] = {}

    for cond, target_freq in CONDITIONS.items():
        if target_freq == 0.0:
            continue  # analyze control separately
        files = condition_files[cond]
        raw = concat_fifs(files)
        results[cond] = {}
        for group_name, channels in GROUPS_4CH.items():
            snrs = snr_per_trial_group(raw, channels, target_freq, TRIAL_DURATION)
            results[cond][group_name] = snrs

    # Also compute "SNR" at each target freq in the control condition
    control_files = condition_files["ssvep_none"]
    control_raw = concat_fifs(control_files)
    control_results: dict[float, dict[str, list[float]]] = {}
    for target_freq in [6.0, 7.5, 10.0, 15.0]:
        control_results[target_freq] = {}
        for group_name, channels in GROUPS_4CH.items():
            snrs = snr_per_trial_group(control_raw, channels, target_freq, TRIAL_DURATION)
            control_results[target_freq][group_name] = snrs

    # Print results table
    print(f"\n{'Condition':>12s} | {'Group':>25s} | {'SNR mean':>8s} | {'SNR std':>7s} | "
          f"{'ctrl SNR':>8s} | {'p(>1)':>7s} | {'det@1.5':>7s} | {'det@2.0':>7s} | {'det@3.0':>7s}")
    print("-" * 120)

    for cond, target_freq in CONDITIONS.items():
        if target_freq == 0.0:
            continue
        for group_name in GROUPS_4CH:
            snrs = results[cond][group_name]
            ctrl_snrs = control_results[target_freq][group_name]
            if not snrs:
                continue
            snr_arr = np.array(snrs)
            ctrl_arr = np.array(ctrl_snrs) if ctrl_snrs else np.array([1.0])
            mean_snr = np.mean(snr_arr)
            std_snr = np.std(snr_arr)
            mean_ctrl = np.mean(ctrl_arr)

            # One-sample t-test: is SNR > 1.0?
            if len(snr_arr) > 1:
                t_stat, p_val = stats.ttest_1samp(snr_arr, 1.0)
                p_val = p_val / 2 if t_stat > 0 else 1.0  # one-sided
            else:
                p_val = 1.0

            det_15 = np.mean(snr_arr > 1.5) * 100
            det_20 = np.mean(snr_arr > 2.0) * 100
            det_30 = np.mean(snr_arr > 3.0) * 100

            p_str = f"{p_val:.4f}" if p_val >= 0.0001 else "<.0001"
            print(f"{cond:>12s} | {group_name:>25s} | {mean_snr:8.2f} | {std_snr:7.2f} | "
                  f"{mean_ctrl:8.2f} | {p_str:>7s} | {det_15:6.0f}% | {det_20:6.0f}% | {det_30:6.0f}%")

    return results, control_results


def analyze_zuna_23ch(condition_files: dict[str, list[Path]]):
    """Run ZUNA on each condition, then analyze SSVEP on 23 channels."""
    print("\n" + "=" * 70)
    print("RUNNING ZUNA SUPERRESOLUTION (5 conditions)")
    print("=" * 70)

    zuna_raws: dict[str, mne.io.Raw] = {}
    for cond in CONDITIONS:
        files = condition_files[cond]
        print(f"\n  [{cond}] Concatenating...")
        raw = concat_fifs(files)
        print(f"  [{cond}] Running ZUNA...")
        zuna_raws[cond] = run_zuna(raw, cond)
        print(f"  [{cond}] Output: {len(zuna_raws[cond].ch_names)} channels, "
              f"{zuna_raws[cond].times[-1]:.1f}s")

    print("\n" + "=" * 70)
    print("ZUNA 23 CHANNELS — PER-TRIAL SSVEP ANALYSIS")
    print("=" * 70)

    results: dict[str, dict[str, list[float]]] = {}

    for cond, target_freq in CONDITIONS.items():
        if target_freq == 0.0:
            continue
        raw = zuna_raws[cond]
        results[cond] = {}
        for group_name, channels in GROUPS_23CH.items():
            snrs = snr_per_trial_group(raw, channels, target_freq, TRIAL_DURATION)
            results[cond][group_name] = snrs

    # Control at each target freq
    control_raw = zuna_raws["ssvep_none"]
    control_results: dict[float, dict[str, list[float]]] = {}
    for target_freq in [6.0, 7.5, 10.0, 15.0]:
        control_results[target_freq] = {}
        for group_name, channels in GROUPS_23CH.items():
            snrs = snr_per_trial_group(control_raw, channels, target_freq, TRIAL_DURATION)
            control_results[target_freq][group_name] = snrs

    # Print results table
    print(f"\n{'Condition':>12s} | {'Group':>25s} | {'SNR mean':>8s} | {'SNR std':>7s} | "
          f"{'ctrl SNR':>8s} | {'p(>1)':>7s} | {'det@1.5':>7s} | {'det@2.0':>7s} | {'det@3.0':>7s}")
    print("-" * 120)

    for cond, target_freq in CONDITIONS.items():
        if target_freq == 0.0:
            continue
        for group_name in GROUPS_23CH:
            snrs = results[cond].get(group_name, [])
            ctrl_snrs = control_results[target_freq].get(group_name, [])
            if not snrs:
                print(f"{cond:>12s} | {group_name:>25s} | {'N/A':>8s} |")
                continue
            snr_arr = np.array(snrs)
            ctrl_arr = np.array(ctrl_snrs) if ctrl_snrs else np.array([1.0])
            mean_snr = np.mean(snr_arr)
            std_snr = np.std(snr_arr)
            mean_ctrl = np.mean(ctrl_arr)

            if len(snr_arr) > 1:
                t_stat, p_val = stats.ttest_1samp(snr_arr, 1.0)
                p_val = p_val / 2 if t_stat > 0 else 1.0
            else:
                p_val = 1.0

            det_15 = np.mean(snr_arr > 1.5) * 100
            det_20 = np.mean(snr_arr > 2.0) * 100
            det_30 = np.mean(snr_arr > 3.0) * 100

            p_str = f"{p_val:.4f}" if p_val >= 0.0001 else "<.0001"
            print(f"{cond:>12s} | {group_name:>25s} | {mean_snr:8.2f} | {std_snr:7.2f} | "
                  f"{mean_ctrl:8.2f} | {p_str:>7s} | {det_15:6.0f}% | {det_20:6.0f}% | {det_30:6.0f}%")

    return results, control_results


def print_summary(
    raw_results: dict[str, dict[str, list[float]]],
    raw_control: dict[float, dict[str, list[float]]],
    zuna_results: dict[str, dict[str, list[float]]],
    zuna_control: dict[float, dict[str, list[float]]],
):
    """Print final summary and verdict."""
    print("\n" + "=" * 70)
    print("SUMMARY: SSVEP DETECTABILITY")
    print("=" * 70)

    print(f"\n{'Freq':>6s} | {'Source':>6s} | {'Group':>25s} | {'SNR':>6s} | {'vs ctrl':>7s} | {'Sig?':>5s}")
    print("-" * 85)

    any_raw_detected = False
    any_zuna_detected = False
    zuna_occ_better = False

    for cond, target_freq in CONDITIONS.items():
        if target_freq == 0.0:
            continue
        freq_str = f"{target_freq:.1f}Hz"

        # Raw 4ch
        for group_name in GROUPS_4CH:
            snrs = raw_results.get(cond, {}).get(group_name, [])
            ctrl = raw_control.get(target_freq, {}).get(group_name, [])
            if not snrs:
                continue
            mean_snr = np.mean(snrs)
            mean_ctrl = np.mean(ctrl) if ctrl else 1.0
            sig = "*" if len(snrs) > 1 and stats.ttest_1samp(snrs, 1.0).statistic > 0 and stats.ttest_1samp(snrs, 1.0).pvalue / 2 < 0.05 else ""
            if sig:
                any_raw_detected = True
            print(f"{freq_str:>6s} | {'raw':>6s} | {group_name:>25s} | {mean_snr:6.2f} | {mean_snr / max(mean_ctrl, 0.01):7.2f} | {sig:>5s}")

        # ZUNA 23ch
        for group_name in GROUPS_23CH:
            snrs = zuna_results.get(cond, {}).get(group_name, [])
            ctrl = zuna_control.get(target_freq, {}).get(group_name, [])
            if not snrs:
                continue
            mean_snr = np.mean(snrs)
            mean_ctrl = np.mean(ctrl) if ctrl else 1.0
            sig = "*" if len(snrs) > 1 and stats.ttest_1samp(snrs, 1.0).statistic > 0 and stats.ttest_1samp(snrs, 1.0).pvalue / 2 < 0.05 else ""
            if sig:
                any_zuna_detected = True
            if sig and group_name == "occipital (O1+O2)":
                zuna_occ_better = True
            print(f"{freq_str:>6s} | {'ZUNA':>6s} | {group_name:>25s} | {mean_snr:6.2f} | {mean_snr / max(mean_ctrl, 0.01):7.2f} | {sig:>5s}")

        print()

    # Verdict
    print("=" * 70)
    print("VERDICT")
    print("=" * 70)

    if any_raw_detected:
        print("\n  Raw 4ch: SSVEP IS detectable at some frequencies on raw Muse channels.")
    else:
        print("\n  Raw 4ch: SSVEP is NOT detectable on raw Muse channels.")

    if zuna_occ_better:
        print("  ZUNA O1+O2: Virtual occipital channels DO show significant SSVEP.")
        print("  -> ZUNA adds meaningful spatial information for SSVEP detection!")
    elif any_zuna_detected:
        print("  ZUNA: Some channels show SSVEP, but NOT specifically at O1+O2.")
        print("  -> ZUNA does not add occipital-specific SSVEP information.")
    else:
        print("  ZUNA: SSVEP is NOT detectable on any ZUNA channels.")
        print("  -> ZUNA does not help with SSVEP from 4 Muse channels.")

    # Compare raw temporal vs ZUNA occipital for the critical test
    print("\n  Critical comparison (raw temporal vs ZUNA occipital):")
    for cond, target_freq in CONDITIONS.items():
        if target_freq == 0.0:
            continue
        raw_temp = raw_results.get(cond, {}).get("temporal (TP9+TP10)", [])
        zuna_occ = zuna_results.get(cond, {}).get("occipital (O1+O2)", [])
        raw_mean = np.mean(raw_temp) if raw_temp else float("nan")
        zuna_mean = np.mean(zuna_occ) if zuna_occ else float("nan")
        winner = "ZUNA O1+O2" if zuna_mean > raw_mean else "Raw TP9+TP10"
        print(f"    {target_freq:5.1f}Hz: Raw temporal SNR={raw_mean:.2f}, "
              f"ZUNA occipital SNR={zuna_mean:.2f} -> {winner}")


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    print("=" * 70)
    print("SSVEP DETECTION EXPERIMENT")
    print("Muse 2 (4ch) vs ZUNA superresolution (23ch)")
    print("=" * 70)

    # Find recordings for all conditions
    condition_files: dict[str, list[Path]] = {}
    for cond in CONDITIONS:
        try:
            files = find_fif_files(cond)
            condition_files[cond] = files
            print(f"  {cond}: {len(files)} trials")
        except FileNotFoundError as e:
            print(f"\nERROR: {e}")
            print(f"Record {cond} protocol first.")
            return

    # Phase 1: Raw 4ch analysis
    raw_results, raw_control = analyze_raw_4ch(condition_files)

    # Phase 2: ZUNA 23ch analysis
    zuna_results, zuna_control = analyze_zuna_23ch(condition_files)

    # Phase 3: Summary
    print_summary(raw_results, raw_control, zuna_results, zuna_control)


if __name__ == "__main__":
    main()
