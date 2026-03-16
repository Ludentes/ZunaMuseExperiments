#!/usr/bin/env python3
"""Evaluate ZUNA's practical value for BCI detectors and beyond.

Analyzes:
1. Blink detector: SNR, amplitude, bilateral correlation
2. Clench detector: temporal EMG preservation
3. New capabilities: drowsiness, focus, spatial patterns
4. SSVEP: frequency-locked responses in virtual channels
5. Alpha asymmetry: emotional valence proxy

Usage:
    PYTHONPATH=. python scripts/eval_zuna_detectors.py
"""
import json
from pathlib import Path

import mne
import numpy as np
from scipy import signal as scipy_signal, stats

mne.set_log_level("ERROR")

RECORDINGS = Path("/home/newub/w/zyphraexps/recordings")

# Channel groups for ZUNA 23ch output
MUSE_FRONTAL = ["AF7", "AF8"]
MUSE_TEMPORAL = ["TP9", "TP10"]
ZUNA_OCCIPITAL = ["O1", "O2"]
ZUNA_PARIETAL = ["P3", "Pz", "P4"]
ZUNA_CENTRAL = ["Cz", "C3", "C4"]
ZUNA_FRONTAL = ["Fp1", "Fp2", "F3", "Fz", "F4", "F7", "F8"]
ZUNA_TEMPORAL = ["T3", "T4", "T5", "T6"]


def load_raw(label: str, kind: str = "raw") -> mne.io.Raw | None:
    """Load raw or zuna output for a label."""
    if kind == "raw":
        path = RECORDINGS / label / "zuna_concat_raw.fif"
    else:
        path = RECORDINGS / label / "zuna_output_raw.fif"
    if not path.exists():
        return None
    return mne.io.read_raw_fif(str(path), preload=True, verbose=False)


def pick_channels(raw: mne.io.Raw, ch_names: list[str]) -> list[str]:
    """Return subset of ch_names that exist in raw."""
    return [ch for ch in ch_names if ch in raw.ch_names]


def bandpower(data: np.ndarray, sfreq: float, band: tuple[float, float]) -> float:
    """Compute average bandpower in a frequency band."""
    freqs, psd = scipy_signal.welch(data, sfreq, nperseg=min(len(data), int(sfreq * 2)))
    idx = np.logical_and(freqs >= band[0], freqs <= band[1])
    if not np.any(idx):
        return 0.0
    return float(np.mean(psd[idx]))


def snr_blink(raw: mne.io.Raw, ch_names: list[str]) -> dict:
    """Measure blink SNR: peak deflection vs baseline noise."""
    picks = pick_channels(raw, ch_names)
    if not picks:
        return {}
    data = raw.get_data(picks=picks) * 1e6  # V -> uV
    sfreq = raw.info["sfreq"]

    results = {}
    for i, ch in enumerate(picks):
        sig = data[i]
        # Baseline noise: median absolute deviation
        baseline_mad = np.median(np.abs(sig - np.median(sig)))
        # Peak deflection: 1st percentile (blinks go negative on frontal)
        peak = np.percentile(sig, 1)
        median_val = np.median(sig)
        deflection = abs(peak - median_val)
        snr = deflection / max(baseline_mad, 0.1)
        results[ch] = {
            "deflection_uv": float(deflection),
            "baseline_mad": float(baseline_mad),
            "snr": float(snr),
            "peak_1pct": float(peak),
            "median": float(median_val),
        }
    return results


def bilateral_corr(raw: mne.io.Raw, ch1: str, ch2: str, window_s: float = 0.5) -> dict:
    """Compute bilateral correlation between two channels in sliding windows."""
    if ch1 not in raw.ch_names or ch2 not in raw.ch_names:
        return {}
    data = raw.get_data(picks=[ch1, ch2]) * 1e6
    sfreq = raw.info["sfreq"]
    win = int(window_s * sfreq)

    corrs = []
    for start in range(0, data.shape[1] - win, win // 2):
        seg1 = data[0, start:start + win]
        seg2 = data[1, start:start + win]
        if np.std(seg1) > 0.1 and np.std(seg2) > 0.1:
            r = np.corrcoef(seg1, seg2)[0, 1]
            corrs.append(r)

    if not corrs:
        return {}
    return {
        "mean_corr": float(np.mean(corrs)),
        "median_corr": float(np.median(corrs)),
        "p10_corr": float(np.percentile(corrs, 10)),
        "p90_corr": float(np.percentile(corrs, 90)),
        "n_windows": len(corrs),
    }


def temporal_emg(raw: mne.io.Raw, ch_names: list[str]) -> dict:
    """Measure high-frequency EMG energy (20-100 Hz) on temporal channels."""
    picks = pick_channels(raw, ch_names)
    if not picks:
        return {}
    data = raw.get_data(picks=picks) * 1e6
    sfreq = raw.info["sfreq"]

    results = {}
    for i, ch in enumerate(picks):
        hf_power = bandpower(data[i], sfreq, (20, min(100, sfreq / 2 - 1)))
        lf_power = bandpower(data[i], sfreq, (1, 10))
        results[ch] = {
            "hf_power": float(hf_power),
            "lf_power": float(lf_power),
            "hf_lf_ratio": float(hf_power / max(lf_power, 1e-6)),
        }
    return results


def ssvep_analysis(raw: mne.io.Raw, target_freq: float, ch_names: list[str]) -> dict:
    """Check for frequency-locked SSVEP response at target frequency."""
    picks = pick_channels(raw, ch_names)
    if not picks:
        return {}
    data = raw.get_data(picks=picks) * 1e6
    sfreq = raw.info["sfreq"]

    results = {}
    for i, ch in enumerate(picks):
        freqs, psd = scipy_signal.welch(data[i], sfreq, nperseg=min(len(data[i]), int(sfreq * 4)))
        # Power at target freq (±0.5 Hz)
        target_idx = np.logical_and(freqs >= target_freq - 0.5, freqs <= target_freq + 0.5)
        # Background: 3-30 Hz excluding target
        bg_idx = np.logical_and(freqs >= 3, freqs <= 30)
        bg_idx = np.logical_and(bg_idx, ~target_idx)

        if not np.any(target_idx) or not np.any(bg_idx):
            continue

        target_power = float(np.max(psd[target_idx]))
        bg_power = float(np.mean(psd[bg_idx]))
        snr = target_power / max(bg_power, 1e-6)

        results[ch] = {
            "target_power": target_power,
            "bg_power": bg_power,
            "snr": float(snr),
            "snr_db": float(10 * np.log10(max(snr, 1e-6))),
        }
    return results


def spatial_coherence(raw: mne.io.Raw, band: tuple[float, float]) -> dict:
    """Compute inter-channel coherence in a frequency band — measures spatial structure."""
    all_chs = pick_channels(raw, ZUNA_FRONTAL + ZUNA_PARIETAL + ZUNA_OCCIPITAL + ZUNA_CENTRAL)
    if len(all_chs) < 2:
        return {}
    data = raw.get_data(picks=all_chs) * 1e6
    sfreq = raw.info["sfreq"]

    # Compute pairwise coherence for a sample of channel pairs
    coherences = []
    n = len(all_chs)
    for i in range(n):
        for j in range(i + 1, n):
            f, coh = scipy_signal.coherence(data[i], data[j], sfreq,
                                             nperseg=min(len(data[i]), int(sfreq * 2)))
            idx = np.logical_and(f >= band[0], f <= band[1])
            if np.any(idx):
                coherences.append(float(np.mean(coh[idx])))

    if not coherences:
        return {}
    return {
        "mean_coherence": float(np.mean(coherences)),
        "std_coherence": float(np.std(coherences)),
        "n_pairs": len(coherences),
    }


def main():
    results = {}

    # ================================================================
    # 1. BLINK DETECTOR ANALYSIS
    # ================================================================
    print("=" * 70)
    print("  1. BLINK DETECTOR: Does ZUNA improve blink detection?")
    print("=" * 70)

    for label in ["single_blink", "double_blink", "blink_continuous"]:
        raw = load_raw(label, "raw")
        zuna = load_raw(label, "zuna")
        if raw is None:
            continue

        print(f"\n  [{label}]")
        key = f"blink_{label}"
        results[key] = {}

        # SNR on frontal channels
        raw_snr = snr_blink(raw, MUSE_FRONTAL)
        print(f"    RAW  frontal SNR:")
        for ch, v in raw_snr.items():
            print(f"      {ch}: deflection={v['deflection_uv']:.1f}µV, MAD={v['baseline_mad']:.1f}, SNR={v['snr']:.1f}")
        results[key]["raw_snr"] = raw_snr

        if zuna:
            zuna_snr = snr_blink(zuna, MUSE_FRONTAL)
            print(f"    ZUNA frontal SNR:")
            for ch, v in zuna_snr.items():
                print(f"      {ch}: deflection={v['deflection_uv']:.1f}µV, MAD={v['baseline_mad']:.1f}, SNR={v['snr']:.1f}")
            results[key]["zuna_snr"] = zuna_snr

            # Check if ZUNA virtual channels also show blink artifact
            virtual_snr = snr_blink(zuna, ZUNA_FRONTAL[:4])
            if virtual_snr:
                print(f"    ZUNA virtual frontal blink propagation:")
                for ch, v in virtual_snr.items():
                    print(f"      {ch}: deflection={v['deflection_uv']:.1f}µV, SNR={v['snr']:.1f}")
            results[key]["zuna_virtual_snr"] = virtual_snr

        # Bilateral correlation (AF7 vs AF8)
        if raw:
            raw_bilat = bilateral_corr(raw, "AF7", "AF8")
            if raw_bilat:
                print(f"    RAW  AF7↔AF8 corr: mean={raw_bilat['mean_corr']:.3f}, median={raw_bilat['median_corr']:.3f}")
            results[key]["raw_bilateral"] = raw_bilat
        if zuna:
            zuna_bilat = bilateral_corr(zuna, "AF7", "AF8")
            if zuna_bilat:
                print(f"    ZUNA AF7↔AF8 corr: mean={zuna_bilat['mean_corr']:.3f}, median={zuna_bilat['median_corr']:.3f}")
            results[key]["zuna_bilateral"] = zuna_bilat

    # ================================================================
    # 2. CLENCH DETECTOR ANALYSIS
    # ================================================================
    print(f"\n{'=' * 70}")
    print("  2. CLENCH DETECTOR: Does ZUNA preserve temporal EMG?")
    print("=" * 70)

    for label in ["clench", "rest", "talk"]:
        raw = load_raw(label, "raw")
        zuna = load_raw(label, "zuna")
        if raw is None:
            continue

        print(f"\n  [{label}]")
        key = f"clench_{label}"
        results[key] = {}

        raw_emg = temporal_emg(raw, MUSE_TEMPORAL)
        print(f"    RAW  temporal EMG:")
        for ch, v in raw_emg.items():
            print(f"      {ch}: HF={v['hf_power']:.1f}, LF={v['lf_power']:.1f}, ratio={v['hf_lf_ratio']:.2f}")
        results[key]["raw_emg"] = raw_emg

        if zuna:
            zuna_emg = temporal_emg(zuna, MUSE_TEMPORAL)
            print(f"    ZUNA temporal EMG:")
            for ch, v in zuna_emg.items():
                print(f"      {ch}: HF={v['hf_power']:.1f}, LF={v['lf_power']:.1f}, ratio={v['hf_lf_ratio']:.2f}")
            results[key]["zuna_emg"] = zuna_emg

            # Check if virtual temporal channels preserve EMG
            zuna_virt_emg = temporal_emg(zuna, ZUNA_TEMPORAL)
            if zuna_virt_emg:
                print(f"    ZUNA virtual temporal EMG:")
                for ch, v in zuna_virt_emg.items():
                    print(f"      {ch}: HF={v['hf_power']:.1f}, ratio={v['hf_lf_ratio']:.2f}")
            results[key]["zuna_virtual_emg"] = zuna_virt_emg

    # ================================================================
    # 3. SSVEP ANALYSIS — can ZUNA enable visual BCI?
    # ================================================================
    print(f"\n{'=' * 70}")
    print("  3. SSVEP: Can ZUNA reveal frequency-locked visual responses?")
    print("=" * 70)

    ssvep_labels = {
        "ssvep_6hz": 6, "ssvep_7hz": 7, "ssvep_10hz": 10, "ssvep_15hz": 15,
        "flicker_3hz": 3, "flicker_4hz": 4, "flicker_5hz": 5, "flicker_6hz": 6,
    }

    for label, freq in ssvep_labels.items():
        raw = load_raw(label, "raw")
        zuna = load_raw(label, "zuna")
        if raw is None:
            continue

        print(f"\n  [{label}] target={freq}Hz")
        key = f"ssvep_{label}"
        results[key] = {}

        # Raw: only have frontal+temporal
        raw_ssvep = ssvep_analysis(raw, freq, MUSE_FRONTAL + MUSE_TEMPORAL)
        best_raw = max((v["snr_db"] for v in raw_ssvep.values()), default=0)
        print(f"    RAW  best SNR: {best_raw:.1f} dB")
        for ch, v in raw_ssvep.items():
            if v["snr_db"] > 3:
                print(f"      {ch}: {v['snr_db']:.1f} dB")
        results[key]["raw"] = raw_ssvep

        if zuna:
            # ZUNA: check occipital (where SSVEP should be strongest)
            zuna_ssvep = ssvep_analysis(zuna, freq,
                                        MUSE_FRONTAL + MUSE_TEMPORAL + ZUNA_OCCIPITAL +
                                        ZUNA_PARIETAL + ZUNA_CENTRAL)
            best_zuna = max((v["snr_db"] for v in zuna_ssvep.values()), default=0)
            print(f"    ZUNA best SNR: {best_zuna:.1f} dB")
            for ch, v in sorted(zuna_ssvep.items(), key=lambda x: -x[1]["snr_db"])[:5]:
                if v["snr_db"] > 3:
                    print(f"      {ch}: {v['snr_db']:.1f} dB")
            results[key]["zuna"] = zuna_ssvep

            # Does ZUNA add occipital SSVEP that raw doesn't have?
            occ = {ch: v for ch, v in zuna_ssvep.items() if ch in ZUNA_OCCIPITAL}
            if occ:
                occ_best = max(v["snr_db"] for v in occ.values())
                print(f"    ZUNA occipital SNR: {occ_best:.1f} dB ({'USEFUL' if occ_best > 6 else 'WEAK' if occ_best > 3 else 'NONE'})")

    # Compare SSVEP vs no-SSVEP baseline
    none_raw = load_raw("ssvep_none", "raw")
    none_zuna = load_raw("ssvep_none", "zuna")
    if none_raw:
        print(f"\n  [ssvep_none — baseline (no stimulus)]")
        for freq in [6, 7, 10, 15]:
            raw_bl = ssvep_analysis(none_raw, freq, MUSE_FRONTAL + MUSE_TEMPORAL)
            best = max((v["snr_db"] for v in raw_bl.values()), default=0)
            print(f"    RAW  {freq}Hz baseline SNR: {best:.1f} dB")
            if none_zuna:
                zuna_bl = ssvep_analysis(none_zuna, freq,
                                         MUSE_FRONTAL + MUSE_TEMPORAL + ZUNA_OCCIPITAL)
                best_z = max((v["snr_db"] for v in zuna_bl.values()), default=0)
                print(f"    ZUNA {freq}Hz baseline SNR: {best_z:.1f} dB")

    # ================================================================
    # 4. DROWSINESS DETECTOR VIABILITY
    # ================================================================
    print(f"\n{'=' * 70}")
    print("  4. DROWSINESS: Can ZUNA enable drowsiness detection?")
    print("=" * 70)

    drowsy = load_raw("drowsy", "zuna")
    rest = load_raw("rest", "zuna")
    drowsy_raw = load_raw("drowsy", "raw")
    rest_raw = load_raw("rest", "raw")

    if drowsy_raw and rest_raw:
        print("\n  RAW 4ch band power comparison (drowsy vs rest):")
        for band_name, band in [("theta", (4, 8)), ("alpha", (8, 13)), ("beta", (13, 30))]:
            d_data = drowsy_raw.get_data(picks=pick_channels(drowsy_raw, MUSE_FRONTAL)) * 1e6
            r_data = rest_raw.get_data(picks=pick_channels(rest_raw, MUSE_FRONTAL)) * 1e6
            d_power = np.mean([bandpower(d_data[i], drowsy_raw.info["sfreq"], band) for i in range(len(d_data))])
            r_power = np.mean([bandpower(r_data[i], rest_raw.info["sfreq"], band) for i in range(len(r_data))])
            ratio = d_power / max(r_power, 1e-6)
            print(f"    {band_name:8s}: drowsy={d_power:.1f}  rest={r_power:.1f}  ratio={ratio:.2f}")

    if drowsy and rest:
        print("\n  ZUNA 23ch band power comparison (drowsy vs rest):")
        all_groups = {
            "frontal_muse": MUSE_FRONTAL,
            "temporal_muse": MUSE_TEMPORAL,
            "occipital": ZUNA_OCCIPITAL,
            "parietal": ZUNA_PARIETAL,
            "central": ZUNA_CENTRAL,
        }
        for group_name, chs in all_groups.items():
            d_picks = pick_channels(drowsy, chs)
            r_picks = pick_channels(rest, chs)
            if not d_picks or not r_picks:
                continue
            d_data = drowsy.get_data(picks=d_picks) * 1e6
            r_data = rest.get_data(picks=r_picks) * 1e6
            print(f"    {group_name}:")
            for band_name, band in [("theta", (4, 8)), ("alpha", (8, 13)), ("beta", (13, 30))]:
                d_power = np.mean([bandpower(d_data[i], drowsy.info["sfreq"], band) for i in range(len(d_data))])
                r_power = np.mean([bandpower(r_data[i], rest.info["sfreq"], band) for i in range(len(r_data))])
                ratio = d_power / max(r_power, 1e-6)
                marker = " ***" if abs(ratio - 1.0) > 0.5 else ""
                print(f"      {band_name:8s}: drowsy={d_power:.1f}  rest={r_power:.1f}  ratio={ratio:.2f}{marker}")

    # ================================================================
    # 5. SPATIAL COHERENCE — is virtual channel data spatially structured?
    # ================================================================
    print(f"\n{'=' * 70}")
    print("  5. SPATIAL STRUCTURE: Are ZUNA virtual channels coherent or noise?")
    print("=" * 70)

    for label in ["eyes_closed", "rest", "meditation", "mental_math"]:
        zuna = load_raw(label, "zuna")
        if zuna is None:
            continue
        print(f"\n  [{label}]")
        for band_name, band in [("alpha", (8, 13)), ("beta", (13, 30)), ("theta", (4, 8))]:
            coh = spatial_coherence(zuna, band)
            if coh:
                print(f"    {band_name:8s} coherence: mean={coh['mean_coherence']:.3f} ± {coh['std_coherence']:.3f} ({coh['n_pairs']} pairs)")

    # ================================================================
    # 6. FOCUS/CONCENTRATION — can ZUNA improve theta/beta metric?
    # ================================================================
    print(f"\n{'=' * 70}")
    print("  6. FOCUS: Does ZUNA improve concentration scoring reliability?")
    print("=" * 70)

    # Compare epoch-level variance of theta/beta ratio
    for label in ["meditation", "mental_math", "rest"]:
        raw = load_raw(label, "raw")
        zuna = load_raw(label, "zuna")
        if raw is None:
            continue

        print(f"\n  [{label}]")
        sfreq = raw.info["sfreq"]
        epoch_s = 5.0
        epoch_n = int(epoch_s * sfreq)

        # Raw: frontal theta/beta per epoch
        raw_picks = pick_channels(raw, MUSE_FRONTAL)
        if raw_picks:
            raw_data = raw.get_data(picks=raw_picks) * 1e6
            raw_mean = np.mean(raw_data, axis=0)
            n_epochs = len(raw_mean) // epoch_n
            raw_tbs = []
            for e in range(n_epochs):
                seg = raw_mean[e * epoch_n:(e + 1) * epoch_n]
                theta = bandpower(seg, sfreq, (4, 8))
                beta = bandpower(seg, sfreq, (13, 30))
                raw_tbs.append(theta / max(beta, 1e-6))
            if raw_tbs:
                print(f"    RAW  frontal θ/β: mean={np.mean(raw_tbs):.2f}, std={np.std(raw_tbs):.2f}, CV={np.std(raw_tbs)/max(np.mean(raw_tbs), 1e-6):.2f} ({n_epochs} epochs)")

        if zuna:
            # ZUNA: frontal + central + parietal
            for group_name, chs in [("frontal_muse", MUSE_FRONTAL), ("central", ZUNA_CENTRAL), ("parietal", ZUNA_PARIETAL)]:
                z_picks = pick_channels(zuna, chs)
                if not z_picks:
                    continue
                z_data = zuna.get_data(picks=z_picks) * 1e6
                z_mean = np.mean(z_data, axis=0)
                n_epochs = len(z_mean) // epoch_n
                z_tbs = []
                for e in range(n_epochs):
                    seg = z_mean[e * epoch_n:(e + 1) * epoch_n]
                    theta = bandpower(seg, sfreq, (4, 8))
                    beta = bandpower(seg, sfreq, (13, 30))
                    z_tbs.append(theta / max(beta, 1e-6))
                if z_tbs:
                    print(f"    ZUNA {group_name:15s} θ/β: mean={np.mean(z_tbs):.2f}, std={np.std(z_tbs):.2f}, CV={np.std(z_tbs)/max(np.mean(z_tbs), 1e-6):.2f} ({n_epochs} epochs)")

    # ================================================================
    # 7. ALPHA ASYMMETRY — emotional valence proxy
    # ================================================================
    print(f"\n{'=' * 70}")
    print("  7. ALPHA ASYMMETRY: Does ZUNA improve frontal asymmetry?")
    print("=" * 70)

    for label in ["eyes_closed", "rest", "meditation", "mental_math"]:
        raw = load_raw(label, "raw")
        zuna = load_raw(label, "zuna")
        if raw is None:
            continue

        print(f"\n  [{label}]")
        sfreq = raw.info["sfreq"]
        epoch_n = int(5.0 * sfreq)

        # Raw FAA: AF8 - AF7 alpha power (log)
        if "AF7" in raw.ch_names and "AF8" in raw.ch_names:
            af7 = raw.get_data(picks=["AF7"])[0] * 1e6
            af8 = raw.get_data(picks=["AF8"])[0] * 1e6
            n_ep = len(af7) // epoch_n
            raw_faas = []
            for e in range(n_ep):
                a7 = bandpower(af7[e * epoch_n:(e + 1) * epoch_n], sfreq, (8, 13))
                a8 = bandpower(af8[e * epoch_n:(e + 1) * epoch_n], sfreq, (8, 13))
                faa = np.log(max(a8, 1e-6)) - np.log(max(a7, 1e-6))
                raw_faas.append(faa)
            if raw_faas:
                print(f"    RAW  FAA (AF8-AF7): mean={np.mean(raw_faas):.3f}, std={np.std(raw_faas):.3f}, CV={np.std(raw_faas)/max(abs(np.mean(raw_faas)), 1e-6):.2f}")

        if zuna and "AF7" in zuna.ch_names and "AF8" in zuna.ch_names:
            af7 = zuna.get_data(picks=["AF7"])[0] * 1e6
            af8 = zuna.get_data(picks=["AF8"])[0] * 1e6
            n_ep = len(af7) // epoch_n
            zuna_faas = []
            for e in range(n_ep):
                a7 = bandpower(af7[e * epoch_n:(e + 1) * epoch_n], sfreq, (8, 13))
                a8 = bandpower(af8[e * epoch_n:(e + 1) * epoch_n], sfreq, (8, 13))
                faa = np.log(max(a8, 1e-6)) - np.log(max(a7, 1e-6))
                zuna_faas.append(faa)
            if zuna_faas:
                print(f"    ZUNA FAA (AF8-AF7): mean={np.mean(zuna_faas):.3f}, std={np.std(zuna_faas):.3f}, CV={np.std(zuna_faas)/max(abs(np.mean(zuna_faas)), 1e-6):.2f}")

            # Also check F4-F3 asymmetry (classic 10-20 FAA)
            if "F3" in zuna.ch_names and "F4" in zuna.ch_names:
                f3 = zuna.get_data(picks=["F3"])[0] * 1e6
                f4 = zuna.get_data(picks=["F4"])[0] * 1e6
                n_ep = len(f3) // epoch_n
                classic_faas = []
                for e in range(n_ep):
                    a3 = bandpower(f3[e * epoch_n:(e + 1) * epoch_n], sfreq, (8, 13))
                    a4 = bandpower(f4[e * epoch_n:(e + 1) * epoch_n], sfreq, (8, 13))
                    faa = np.log(max(a4, 1e-6)) - np.log(max(a3, 1e-6))
                    classic_faas.append(faa)
                if classic_faas:
                    print(f"    ZUNA FAA (F4-F3):  mean={np.mean(classic_faas):.3f}, std={np.std(classic_faas):.3f}, CV={np.std(classic_faas)/max(abs(np.mean(classic_faas)), 1e-6):.2f}")

    # ================================================================
    # PRACTICAL SUMMARY
    # ================================================================
    print(f"\n{'=' * 70}")
    print("  PRACTICAL SUMMARY")
    print("=" * 70)
    print("""
    EXISTING DETECTORS:
    1. Blink Detector  — see SNR comparison above
    2. Clench Detector — see temporal EMG preservation above
    3. Speech Guard    — see temporal HF analysis above

    NEW CAPABILITIES (ZUNA-ENABLED):
    4. SSVEP BCI       — see occipital SNR analysis above
    5. Drowsiness      — see band power ratios above
    6. Focus Scoring   — see θ/β stability above
    7. Alpha Asymmetry — see FAA comparison above
    8. Spatial Coherence — see coherence analysis above
    """)

    # Save results
    out_path = Path("experiments/zuna_detector_eval.json")
    out_path.parent.mkdir(exist_ok=True)

    # Convert numpy types for JSON serialization
    def convert(obj):
        if isinstance(obj, (np.float64, np.float32)):
            return float(obj)
        if isinstance(obj, (np.int64, np.int32)):
            return int(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return obj

    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=convert)
    print(f"\n  Results saved to {out_path}")


if __name__ == "__main__":
    main()
