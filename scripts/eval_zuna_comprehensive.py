#!/usr/bin/env python3
"""Comprehensive ZUNA evaluation: does superresolution add practical value?

Runs after batch_zuna.py has processed all recordings.
Compares raw 4ch vs ZUNA 23ch across every testable contrast.

Usage:
    PYTHONPATH=. python scripts/eval_zuna_comprehensive.py
"""
import json
from pathlib import Path

import mne
import numpy as np
from scipy.signal import welch
from scipy.stats import ttest_ind

mne.set_log_level("ERROR")

RECORDINGS = Path("/home/newub/w/zyphraexps/recordings")

MUSE_CH = ["TP9", "AF7", "AF8", "TP10"]
CHANNEL_GROUPS = {
    "frontal_muse": ["AF7", "AF8"],
    "temporal_muse": ["TP9", "TP10"],
    "occipital": ["O1", "O2"],
    "parietal": ["P3", "Pz", "P4"],
    "central": ["C3", "Cz", "C4"],
    "frontal_virtual": ["Fp1", "Fp2", "F3", "Fz", "F4"],
    "temporal_virtual": ["T3", "T4", "T5", "T6"],
}


def band_power(data_uv: np.ndarray, sr: int, lo: float, hi: float) -> float:
    """Band power in µV² via Welch."""
    freqs, psd = welch(data_uv, fs=sr, nperseg=min(1024, len(data_uv)))
    idx = (freqs >= lo) & (freqs <= hi)
    return float(np.trapezoid(psd[idx], freqs[idx]))


def band_powers_all(raw: mne.io.Raw) -> dict:
    """Compute band powers for all channel groups."""
    data_uv = raw.get_data() * 1e6
    sr = int(raw.info["sfreq"])
    bands = {"delta": (1, 4), "theta": (4, 8), "alpha": (8, 13), "beta": (13, 30), "gamma": (30, 50)}
    result = {}
    for gname, channels in CHANNEL_GROUPS.items():
        available = [ch for ch in channels if ch in raw.ch_names]
        if not available:
            continue
        group_bp = {b: [] for b in bands}
        for ch in available:
            idx = raw.ch_names.index(ch)
            for bname, (lo, hi) in bands.items():
                group_bp[bname].append(band_power(data_uv[idx], sr, lo, hi))
        result[gname] = {b: float(np.mean(v)) for b, v in group_bp.items() if v}
        result[gname]["channels"] = available
    return result


def epoch_band_powers(raw: mne.io.Raw, epoch_len: float = 5.0) -> dict[str, list[dict]]:
    """Compute band powers in non-overlapping epochs for statistical tests."""
    data_uv = raw.get_data() * 1e6
    sr = int(raw.info["sfreq"])
    n_samples = int(epoch_len * sr)
    n_epochs = data_uv.shape[1] // n_samples
    bands = {"delta": (1, 4), "theta": (4, 8), "alpha": (8, 13), "beta": (13, 30), "gamma": (30, 50)}

    result = {}
    for gname, channels in CHANNEL_GROUPS.items():
        available = [ch for ch in channels if ch in raw.ch_names]
        if not available:
            continue
        epoch_list = []
        for ep in range(n_epochs):
            start = ep * n_samples
            end = start + n_samples
            bp = {}
            for bname, (lo, hi) in bands.items():
                vals = []
                for ch in available:
                    idx = raw.ch_names.index(ch)
                    vals.append(band_power(data_uv[idx, start:end], sr, lo, hi))
                bp[bname] = float(np.mean(vals))
            # Derived metrics
            bp["theta_beta"] = bp["theta"] / max(bp["beta"], 0.001)
            bp["alpha_beta"] = bp["alpha"] / max(bp["beta"], 0.001)
            epoch_list.append(bp)
        result[gname] = epoch_list
    return result


def load_pair(label: str) -> tuple[mne.io.Raw | None, mne.io.Raw | None]:
    """Load raw concatenated + ZUNA output for a label."""
    concat_path = RECORDINGS / label / "zuna_concat_raw.fif"
    zuna_path = RECORDINGS / label / "zuna_output_raw.fif"
    raw = mne.io.read_raw_fif(str(concat_path), preload=True, verbose=False) if concat_path.exists() else None
    zuna = mne.io.read_raw_fif(str(zuna_path), preload=True, verbose=False) if zuna_path.exists() else None
    return raw, zuna


def cohens_d(a: np.ndarray, b: np.ndarray) -> float:
    """Cohen's d effect size."""
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return 0.0
    pooled_std = np.sqrt(((na - 1) * np.var(a, ddof=1) + (nb - 1) * np.var(b, ddof=1)) / (na + nb - 2))
    if pooled_std < 1e-10:
        return 0.0
    return float((np.mean(a) - np.mean(b)) / pooled_std)


def discrimination_test(label_a: str, label_b: str, metric: str, groups: list[str]) -> dict:
    """Test how well a metric discriminates two conditions, raw vs ZUNA."""
    raw_a, zuna_a = load_pair(label_a)
    raw_b, zuna_b = load_pair(label_b)
    if not all([raw_a, raw_b]):
        return {"error": "missing raw data"}

    results = {}
    for source_name, data_a, data_b in [("raw_4ch", raw_a, raw_b), ("zuna_23ch", zuna_a, zuna_b)]:
        if data_a is None or data_b is None:
            results[source_name] = {"error": "missing data"}
            continue

        ep_a = epoch_band_powers(data_a)
        ep_b = epoch_band_powers(data_b)

        source_results = {}
        for group in groups:
            if group not in ep_a or group not in ep_b:
                continue
            vals_a = np.array([ep[metric] for ep in ep_a[group]])
            vals_b = np.array([ep[metric] for ep in ep_b[group]])
            if len(vals_a) < 2 or len(vals_b) < 2:
                continue
            d = cohens_d(vals_a, vals_b)
            t, p = ttest_ind(vals_a, vals_b)
            source_results[group] = {
                "mean_a": float(np.mean(vals_a)),
                "mean_b": float(np.mean(vals_b)),
                "d": d,
                "p": p,
                "n_a": len(vals_a),
                "n_b": len(vals_b),
            }
        results[source_name] = source_results
    return results


def print_discrimination(title: str, label_a: str, label_b: str, metric: str, groups: list[str]):
    """Print discrimination test results."""
    results = discrimination_test(label_a, label_b, metric, groups)
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"  {label_a} vs {label_b} — metric: {metric}")
    print(f"{'='*70}")

    if "error" in results:
        print(f"  ERROR: {results['error']}")
        return results

    header = f"  {'Group':30s} | {'Mean A':>8s} | {'Mean B':>8s} | {'d':>6s} | {'p':>8s} | {'Verdict':>10s}"
    for source_name in ["raw_4ch", "zuna_23ch"]:
        print(f"\n  --- {source_name} ---")
        if "error" in results.get(source_name, {}):
            print(f"  {results[source_name]['error']}")
            continue
        print(header)
        print("  " + "-" * 78)
        for group, r in results.get(source_name, {}).items():
            d = r["d"]
            p = r["p"]
            verdict = "STRONG" if abs(d) > 0.8 else "MEDIUM" if abs(d) > 0.5 else "WEAK" if abs(d) > 0.2 else "NONE"
            sig = "*" if p < 0.05 else ""
            print(f"  {group:30s} | {r['mean_a']:8.2f} | {r['mean_b']:8.2f} | {d:6.2f} | {p:8.4f}{sig:1s} | {verdict:>10s}")

    return results


def eval_blink_amplitude():
    """Check how much ZUNA attenuates blink amplitude."""
    print(f"\n{'='*70}")
    print(f"  BLINK AMPLITUDE PRESERVATION")
    print(f"{'='*70}")

    raw, zuna = load_pair("single_blink")
    if raw is None:
        print("  No single_blink data")
        return

    # Compute peak-to-peak on AF7/AF8 for raw
    data_raw = raw.get_data() * 1e6
    for ch_name in ["AF7", "AF8"]:
        if ch_name in raw.ch_names:
            idx = raw.ch_names.index(ch_name)
            ptp_raw = float(np.ptp(data_raw[idx]))
            print(f"  Raw {ch_name} peak-to-peak: {ptp_raw:.1f} µV")

    if zuna is not None:
        data_zuna = zuna.get_data() * 1e6
        for ch_name in ["AF7", "AF8"]:
            if ch_name in zuna.ch_names:
                idx = zuna.ch_names.index(ch_name)
                ptp_zuna = float(np.ptp(data_zuna[idx]))
                print(f"  ZUNA {ch_name} peak-to-peak: {ptp_zuna:.1f} µV")
                if ch_name in raw.ch_names:
                    raw_idx = raw.ch_names.index(ch_name)
                    ptp_raw = float(np.ptp(data_raw[raw_idx]))
                    ratio = ptp_zuna / max(ptp_raw, 0.01)
                    print(f"    Attenuation: {ratio:.2f}x ({(1-ratio)*100:.0f}% loss)")
    else:
        print("  No ZUNA output for single_blink")


def eval_frontal_asymmetry():
    """Test frontal alpha asymmetry (FAA) with ZUNA."""
    print(f"\n{'='*70}")
    print(f"  FRONTAL ALPHA ASYMMETRY")
    print(f"{'='*70}")

    for label in ["eyes_closed", "rest", "meditation", "mental_math"]:
        raw, zuna = load_pair(label)
        if raw is None:
            continue

        data_raw = raw.get_data() * 1e6
        sr = int(raw.info["sfreq"])

        for source_name, data_obj in [("raw", raw), ("zuna", zuna)]:
            if data_obj is None:
                continue
            data = data_obj.get_data() * 1e6
            ch_names = data_obj.ch_names
            if "AF7" in ch_names and "AF8" in ch_names:
                af7_alpha = band_power(data[ch_names.index("AF7")], sr, 8, 13)
                af8_alpha = band_power(data[ch_names.index("AF8")], sr, 8, 13)
                faa = np.log(af8_alpha + 0.01) - np.log(af7_alpha + 0.01)
                print(f"  {label:15s} {source_name:5s}: FAA={faa:+.3f}  AF7={af7_alpha:.1f}  AF8={af8_alpha:.1f}")


def eval_concentration_metric():
    """Test theta/beta ratio as concentration metric, raw vs ZUNA."""
    print(f"\n{'='*70}")
    print(f"  CONCENTRATION METRIC (theta/beta ratio)")
    print(f"  Lower = more concentrated")
    print(f"{'='*70}")

    labels = ["rest", "meditation", "mental_math", "drowsy", "eyes_closed", "eyes_open"]
    for label in labels:
        raw, zuna = load_pair(label)
        if raw is None:
            continue
        for source_name, data_obj in [("raw", raw), ("zuna", zuna)]:
            if data_obj is None:
                continue
            bp = band_powers_all(data_obj)
            for group in ["frontal_muse", "frontal_virtual", "central"]:
                if group in bp:
                    tb = bp[group]["theta"] / max(bp[group]["beta"], 0.001)
                    print(f"  {label:15s} {source_name:5s} {group:20s}: θ/β={tb:.2f}")


def eval_topographic_spread():
    """Check if ZUNA produces spatially distinct patterns across channel groups."""
    print(f"\n{'='*70}")
    print(f"  TOPOGRAPHIC SPREAD (spatial distinctness)")
    print(f"  Higher variance across groups = more spatial info")
    print(f"{'='*70}")

    for label in ["eyes_closed", "rest", "meditation", "mental_math"]:
        _, zuna = load_pair(label)
        if zuna is None:
            continue
        bp = band_powers_all(zuna)
        for band in ["alpha", "beta", "theta"]:
            values = [bp[g][band] for g in bp if band in bp[g]]
            if len(values) >= 3:
                cv = np.std(values) / max(np.mean(values), 0.001)
                print(f"  {label:15s} {band:6s}: CV={cv:.2f} (spread across {len(values)} groups)")


def main():
    print("=" * 70)
    print("COMPREHENSIVE ZUNA EVALUATION")
    print("=" * 70)

    # Check available data
    available = []
    for d in sorted(RECORDINGS.iterdir()):
        if d.is_dir():
            has_raw = (d / "zuna_concat_raw.fif").exists()
            has_zuna = (d / "zuna_output_raw.fif").exists()
            if has_raw or has_zuna:
                available.append((d.name, has_raw, has_zuna))
    print(f"\nAvailable labels ({len(available)}):")
    for label, has_raw, has_zuna in available:
        status = "raw+zuna" if has_raw and has_zuna else "raw only" if has_raw else "zuna only"
        print(f"  {label:25s} {status}")

    if not available:
        print("\nNo processed data. Run batch_zuna.py first.")
        return

    all_results = {}

    # === TEST 1: Alpha blocking (EC vs EO) ===
    r = print_discrimination(
        "ALPHA BLOCKING (eyes closed vs open)",
        "eyes_closed", "eyes_open", "alpha",
        ["frontal_muse", "temporal_muse", "occipital", "parietal", "central"],
    )
    all_results["alpha_blocking"] = r

    # === TEST 2: Meditation vs Mental Math ===
    r = print_discrimination(
        "MEDITATION vs MENTAL MATH",
        "meditation", "mental_math", "theta_beta",
        ["frontal_muse", "frontal_virtual", "central", "parietal", "occipital"],
    )
    all_results["meditation_vs_math"] = r

    # === TEST 3: Drowsy vs Rest ===
    r = print_discrimination(
        "DROWSY vs REST",
        "drowsy", "rest", "alpha",
        ["frontal_muse", "temporal_muse", "occipital", "parietal", "central"],
    )
    all_results["drowsy_vs_rest_alpha"] = r

    r = print_discrimination(
        "DROWSY vs REST (theta)",
        "drowsy", "rest", "theta",
        ["frontal_muse", "temporal_muse", "occipital", "parietal", "central"],
    )
    all_results["drowsy_vs_rest_theta"] = r

    r = print_discrimination(
        "DROWSY vs REST (theta/beta)",
        "drowsy", "rest", "theta_beta",
        ["frontal_muse", "frontal_virtual", "central"],
    )
    all_results["drowsy_vs_rest_tb"] = r

    # === TEST 4: Rest vs Mental Math (concentration) ===
    r = print_discrimination(
        "REST vs MENTAL MATH (concentration proxy)",
        "rest", "mental_math", "theta_beta",
        ["frontal_muse", "frontal_virtual", "central"],
    )
    all_results["rest_vs_math"] = r

    # === TEST 5: Blink amplitude ===
    eval_blink_amplitude()

    # === TEST 6: Frontal asymmetry ===
    eval_frontal_asymmetry()

    # === TEST 7: Concentration metric across conditions ===
    eval_concentration_metric()

    # === TEST 8: Topographic spread ===
    eval_topographic_spread()

    # === SUMMARY ===
    print(f"\n{'='*70}")
    print("PRACTICAL VALUE SUMMARY")
    print(f"{'='*70}")
    print("""
Key questions answered:
1. Does ZUNA improve alpha blocking discrimination? → Check alpha_blocking results
2. Does ZUNA help meditation/math separation?       → Check meditation_vs_math results
3. Can ZUNA enable drowsiness detection?             → Check drowsy_vs_rest results
4. Does ZUNA improve concentration scoring?          → Check rest_vs_math results
5. Does ZUNA preserve blink amplitude?               → Check blink section
6. Does ZUNA add spatial information?                → Check topographic spread

Decision framework:
  - d > 0.8 = large effect → PRACTICAL USE
  - d 0.5-0.8 = medium → POSSIBLE USE with smoothing
  - d 0.2-0.5 = small → NOT RELIABLE for single-trial
  - d < 0.2 = negligible → NO VALUE
""")

    # Save results
    output_path = Path("experiments/zuna_comprehensive_eval.json")
    output_path.parent.mkdir(exist_ok=True)
    # Convert numpy types for JSON
    def to_serializable(obj):
        if isinstance(obj, (np.floating, np.integer)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, dict):
            return {k: to_serializable(v) for k, v in obj.items()}
        return obj

    with open(output_path, "w") as f:
        json.dump(to_serializable(all_results), f, indent=2)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
