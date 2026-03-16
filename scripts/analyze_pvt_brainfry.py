#!/usr/bin/env python3
"""Preliminary Brain Fry analysis: EEG fatigue markers across PVT sessions.

Compares theta/beta ratio, alpha power, frontal asymmetry across sessions
recorded at different times to see if fatigue biomarkers drift.

Usage:
    PYTHONPATH=. python scripts/analyze_pvt_brainfry.py
"""

import json
import numpy as np
from pathlib import Path
from scipy import signal

RECORDING_DIR = Path("recordings/pvt_brainfry")
SFREQ = 256
CH_NAMES = ["TP9", "AF7", "AF8", "TP10"]
# Channel indices
AF7, AF8 = 1, 2  # frontal
TP9, TP10 = 0, 3  # temporal

# PVT: ignore RTs above this threshold (distraction, not fatigue)
RT_CUTOFF_MS = 500


def bandpower(data: np.ndarray, sfreq: float, band: tuple[float, float]) -> float:
    """Compute average bandpower in a frequency band using Welch's method."""
    freqs, psd = signal.welch(data, sfreq, nperseg=min(len(data), sfreq * 2))
    idx = np.logical_and(freqs >= band[0], freqs <= band[1])
    return np.mean(psd[idx]) if np.any(idx) else 0.0


def compute_eeg_features(eeg: np.ndarray, sfreq: float) -> dict:
    """Compute fatigue-relevant EEG features from 4-channel data."""
    # Band definitions
    theta = (4, 8)
    alpha = (8, 13)
    beta = (13, 30)

    features = {}

    # Per-channel bandpowers
    for ch_idx, ch_name in enumerate(CH_NAMES):
        features[f"{ch_name}_theta"] = bandpower(eeg[ch_idx], sfreq, theta)
        features[f"{ch_name}_alpha"] = bandpower(eeg[ch_idx], sfreq, alpha)
        features[f"{ch_name}_beta"] = bandpower(eeg[ch_idx], sfreq, beta)

    # Frontal theta/beta ratio (key fatigue marker)
    frontal_theta = np.mean([features["AF7_theta"], features["AF8_theta"]])
    frontal_beta = np.mean([features["AF7_beta"], features["AF8_beta"]])
    features["frontal_theta_beta_ratio"] = frontal_theta / frontal_beta if frontal_beta > 0 else 0

    # Global theta/beta
    all_theta = np.mean([features[f"{ch}_theta"] for ch in CH_NAMES])
    all_beta = np.mean([features[f"{ch}_beta"] for ch in CH_NAMES])
    features["global_theta_beta_ratio"] = all_theta / all_beta if all_beta > 0 else 0

    # Frontal alpha power (engagement inverse)
    features["frontal_alpha"] = np.mean([features["AF7_alpha"], features["AF8_alpha"]])

    # Frontal alpha asymmetry (FAA) — ln(right) - ln(left)
    r_alpha = features["AF8_alpha"]
    l_alpha = features["AF7_alpha"]
    if r_alpha > 0 and l_alpha > 0:
        features["faa"] = np.log(r_alpha) - np.log(l_alpha)
    else:
        features["faa"] = 0.0

    # Temporal alpha (drowsiness indicator)
    features["temporal_alpha"] = np.mean([features["TP9_alpha"], features["TP10_alpha"]])

    # Theta power trend (absolute)
    features["global_theta"] = all_theta
    features["global_beta"] = all_beta

    return features


def analyze_pvt_json(pvt_path: Path) -> dict:
    """Analyze PVT behavioral results with RT cutoff."""
    with open(pvt_path) as f:
        data = json.load(f)

    responses = data.get("responses", [])
    # Valid responses: rt > 0 and rt <= cutoff
    valid_rts = [r["rt_ms"] for r in responses if 0 < r["rt_ms"] <= RT_CUTOFF_MS]
    all_valid = [r["rt_ms"] for r in responses if r["rt_ms"] > 0]
    excluded = [r["rt_ms"] for r in responses if r["rt_ms"] > RT_CUTOFF_MS]
    lapses = sum(1 for r in responses if r["rt_ms"] == -1)
    false_starts = sum(1 for r in responses if r["rt_ms"] == -2)

    result = {
        "n_total": len(responses),
        "n_valid": len(valid_rts),
        "n_excluded_slow": len(excluded),
        "n_lapses": lapses,
        "n_false_starts": false_starts,
    }

    if valid_rts:
        result["mean_rt"] = np.mean(valid_rts)
        result["median_rt"] = np.median(valid_rts)
        result["fastest_rt"] = np.min(valid_rts)
        result["slowest_rt"] = np.max(valid_rts)
        result["std_rt"] = np.std(valid_rts)
    else:
        result["mean_rt"] = result["median_rt"] = result["fastest_rt"] = 0
        result["slowest_rt"] = result["std_rt"] = 0

    if excluded:
        result["excluded_rts"] = [round(r, 1) for r in excluded]

    note = data.get("note", "")
    if note:
        result["note"] = note

    return result


def segment_eeg_features(eeg: np.ndarray, sfreq: float, segment_s: int = 30) -> list[dict]:
    """Compute features in time segments to see within-session trends."""
    n_samples = eeg.shape[1]
    segment_samples = int(segment_s * sfreq)
    segments = []
    for start in range(0, n_samples, segment_samples):
        end = min(start + segment_samples, n_samples)
        if end - start < sfreq * 5:  # skip segments < 5s
            continue
        seg_features = compute_eeg_features(eeg[:, start:end], sfreq)
        seg_features["start_s"] = start / sfreq
        seg_features["end_s"] = end / sfreq
        segments.append(seg_features)
    return segments


def main():
    sessions = sorted(RECORDING_DIR.iterdir())
    if not sessions:
        print("No PVT sessions found!")
        return

    print("=" * 70)
    print("BRAIN FRY — Preliminary EEG Fatigue Analysis")
    print("=" * 70)
    print(f"Sessions: {len(sessions)}")
    print(f"RT cutoff: >{RT_CUTOFF_MS}ms excluded (distraction)")
    print()

    all_features = []
    session_times = []

    for s_dir in sessions:
        npz_files = list(s_dir.glob("*.npz"))
        pvt_files = list(s_dir.glob("pvt_*.json"))
        if not npz_files:
            continue

        # Parse session time from directory name
        dirname = s_dir.name.rstrip(".")
        try:
            hour = int(dirname[8:10])
            minute = int(dirname[10:12])
            time_str = f"{hour:02d}:{minute:02d}"
            time_minutes = hour * 60 + minute
        except (ValueError, IndexError):
            time_str = "??"
            time_minutes = 0

        # Load EEG
        d = np.load(npz_files[0], allow_pickle=True)
        eeg = d["eeg"]
        sfreq = float(d["sfreq"]) if "sfreq" in d else SFREQ

        print(f"── Session @ {time_str} ──")
        print(f"   EEG: {eeg.shape[1] / sfreq:.0f}s, {eeg.shape[0]}ch @ {sfreq}Hz")

        # Compute features
        features = compute_eeg_features(eeg, sfreq)
        features["time_str"] = time_str
        features["time_minutes"] = time_minutes

        # Within-session segments (30s windows)
        segments = segment_eeg_features(eeg, sfreq, segment_s=30)

        print(f"   Theta/Beta (frontal): {features['frontal_theta_beta_ratio']:.3f}")
        print(f"   Theta/Beta (global):  {features['global_theta_beta_ratio']:.3f}")
        print(f"   Frontal Alpha:        {features['frontal_alpha']:.2f} µV²/Hz")
        print(f"   FAA:                  {features['faa']:.3f}")
        print(f"   Temporal Alpha:       {features['temporal_alpha']:.2f} µV²/Hz")

        if len(segments) > 1:
            tb_start = segments[0]["frontal_theta_beta_ratio"]
            tb_end = segments[-1]["frontal_theta_beta_ratio"]
            print(f"   θ/β within-session:   {tb_start:.3f} → {tb_end:.3f} "
                  f"({'↑' if tb_end > tb_start else '↓'} {abs(tb_end - tb_start) / tb_start * 100:.0f}%)")

        # PVT results
        if pvt_files:
            pvt = analyze_pvt_json(pvt_files[0])
            features["pvt"] = pvt
            print(f"   PVT: median={pvt['median_rt']:.0f}ms, mean={pvt['mean_rt']:.0f}ms, "
                  f"n={pvt['n_valid']}, excluded={pvt['n_excluded_slow']}, "
                  f"lapses={pvt['n_lapses']}, false_starts={pvt['n_false_starts']}")
            if pvt.get("note"):
                print(f"   Note: {pvt['note']}")
            if "excluded_rts" in pvt:
                print(f"   Excluded RTs: {pvt['excluded_rts']}")

        all_features.append(features)
        session_times.append(time_minutes)
        print()

    if len(all_features) < 2:
        print("Need at least 2 sessions for trend analysis.")
        return

    # ── Trend Analysis ──
    print("=" * 70)
    print("TREND ANALYSIS (across sessions)")
    print("=" * 70)

    # Sort by time
    sorted_features = sorted(all_features, key=lambda f: f["time_minutes"])

    print("\nTime   │ θ/β frontal │ θ/β global │ Fr.Alpha │ FAA    │ Temp.Alpha")
    print("───────┼─────────────┼────────────┼──────────┼────────┼───────────")
    for f in sorted_features:
        print(f"{f['time_str']:>6} │ {f['frontal_theta_beta_ratio']:>11.3f} │ "
              f"{f['global_theta_beta_ratio']:>10.3f} │ {f['frontal_alpha']:>8.2f} │ "
              f"{f['faa']:>6.3f} │ {f['temporal_alpha']:>9.2f}")

    # Compute trends
    times = np.array([f["time_minutes"] for f in sorted_features])
    times_h = (times - times[0]) / 60  # hours from first session

    metrics = {
        "frontal_theta_beta_ratio": "Frontal θ/β",
        "global_theta_beta_ratio": "Global θ/β",
        "frontal_alpha": "Frontal Alpha",
        "temporal_alpha": "Temporal Alpha",
        "faa": "FAA",
    }

    print("\n── Linear trends (per hour) ──")
    for key, label in metrics.items():
        values = np.array([f[key] for f in sorted_features])
        if len(times_h) >= 2:
            slope, intercept = np.polyfit(times_h, values, 1)
            r = np.corrcoef(times_h, values)[0, 1] if len(times_h) > 2 else 0
            pct_change = (slope / np.mean(values) * 100) if np.mean(values) != 0 else 0
            direction = "↑" if slope > 0 else "↓"
            print(f"  {label:>20}: {direction} {abs(pct_change):.1f}%/hr "
                  f"(slope={slope:.4f}, r={r:.2f})")

    # First vs Last comparison
    first = sorted_features[0]
    last = sorted_features[-1]
    hours_diff = (last["time_minutes"] - first["time_minutes"]) / 60
    print(f"\n── First ({first['time_str']}) vs Last ({last['time_str']}) — {hours_diff:.1f}h gap ──")
    for key, label in metrics.items():
        v1 = first[key]
        v2 = last[key]
        if v1 != 0:
            pct = (v2 - v1) / abs(v1) * 100
            print(f"  {label:>20}: {v1:.3f} → {v2:.3f} ({pct:+.1f}%)")

    # ── Verdict ──
    print("\n" + "=" * 70)
    print("VERDICT")
    print("=" * 70)

    tb_values = [f["frontal_theta_beta_ratio"] for f in sorted_features]
    tb_slope = np.polyfit(times_h, tb_values, 1)[0] if len(times_h) >= 2 else 0

    if tb_slope > 0:
        print(f"✓ Frontal θ/β INCREASES over time ({tb_slope:.4f}/hr)")
        print("  This is consistent with cognitive fatigue accumulation.")
        if abs(tb_slope / np.mean(tb_values) * 100) > 5:
            print("  Effect size is meaningful (>5%/hr).")
        else:
            print("  Effect size is small (<5%/hr) — may need longer sessions.")
    else:
        print(f"✗ Frontal θ/β DECREASES over time ({tb_slope:.4f}/hr)")
        print("  Unexpected — possible confounds: caffeine, arousal, fit quality.")

    alpha_values = [f["frontal_alpha"] for f in sorted_features]
    alpha_slope = np.polyfit(times_h, alpha_values, 1)[0] if len(times_h) >= 2 else 0
    if alpha_slope > 0:
        print(f"✓ Frontal alpha INCREASES ({alpha_slope:.4f}/hr) — reduced engagement")
    else:
        print(f"  Frontal alpha decreases — sustained engagement or increasing arousal")

    # Save results
    output = {
        "sessions": [{k: v for k, v in f.items() if k != "pvt"} for f in sorted_features],
        "pvt_sessions": [{**f["pvt"], "time": f["time_str"]}
                         for f in sorted_features if "pvt" in f],
        "trends": {
            key: {
                "values": [f[key] for f in sorted_features],
                "times_h": times_h.tolist(),
            }
            for key in metrics
        },
        "rt_cutoff_ms": RT_CUTOFF_MS,
    }

    out_path = Path("experiments/pvt_brainfry_analysis.json")
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
