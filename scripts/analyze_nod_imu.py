"""Analyze IMU nod recordings to characterize nod_yes vs nod_no vs head_still.

Muse 2 IMU channels (BrainFlow):
  accel: ch0=x(lateral), ch1=y(forward), ch2=z(vertical) — in g's
  gyro:  ch3=roll, ch4=pitch(nod), ch5=yaw(shake) — in deg/s

Usage:
    PYTHONPATH=. python scripts/analyze_nod_imu.py
"""
import glob
from pathlib import Path

import numpy as np


def load_imu_trials(label: str) -> list[dict]:
    trials = []
    for f in sorted(glob.glob(f"recordings/{label}/*/{label}_t*.npz")):
        trials.append(_load(f))
    for f in sorted(glob.glob(f"recordings/{label}/{label}_t*.npz")):
        trials.append(_load(f))
    return [t for t in trials if t is not None]


def _load(path: str) -> dict | None:
    try:
        d = np.load(path)
        imu = d.get("imu")
        if imu is None or imu.size == 0:
            return None
        return {
            "imu": imu.astype(np.float64),
            "imu_sfreq": int(d["imu_sfreq"]) if "imu_sfreq" in d else 52,
            "cue_time_ms": int(d["cue_time_ms"]) if "cue_time_ms" in d else 0,
            "path": path,
        }
    except Exception as e:
        print(f"  Error loading {path}: {e}")
        return None


CH_NAMES = ["accel_x", "accel_y", "accel_z", "gyro_roll", "gyro_pitch", "gyro_yaw"]


def analyze_channel_stats(label: str, trials: list[dict]):
    """Per-channel statistics for a set of trials."""
    if not trials:
        print(f"  {label}: no IMU data")
        return

    print(f"\n{'='*70}")
    print(f"{label.upper()} — {len(trials)} trials, sfreq={trials[0]['imu_sfreq']}Hz")
    print(f"{'='*70}")

    for ch_idx, ch_name in enumerate(CH_NAMES):
        ranges = []
        peaks = []
        rms_vals = []
        for trial in trials:
            imu = trial["imu"]
            if ch_idx >= imu.shape[0]:
                continue
            signal = imu[ch_idx]
            signal_centered = signal - np.mean(signal)
            ranges.append(np.ptp(signal))
            peaks.append(np.max(np.abs(signal_centered)))
            rms_vals.append(np.sqrt(np.mean(signal_centered ** 2)))

        ranges = np.array(ranges)
        peaks = np.array(peaks)
        rms_vals = np.array(rms_vals)
        print(f"  {ch_name:12s}  range: {np.median(ranges):7.2f} (p5={np.percentile(ranges,5):6.2f}, p95={np.percentile(ranges,95):6.2f})  "
              f"peak: {np.median(peaks):7.2f}  rms: {np.median(rms_vals):6.2f}")


def find_discriminating_features(nod_yes, nod_no, still):
    """Find which channels/features best separate nod types."""
    print(f"\n{'='*70}")
    print("DISCRIMINATING FEATURES")
    print(f"{'='*70}")

    # For each channel, compute features that might distinguish nods
    features = {}
    for label, trials in [("nod_yes", nod_yes), ("nod_no", nod_no), ("still", still)]:
        features[label] = {"peak_abs": [], "rms": [], "range": [], "zero_crossings": []}
        for ch_idx, ch_name in enumerate(CH_NAMES):
            for trial in trials:
                imu = trial["imu"]
                if ch_idx >= imu.shape[0]:
                    continue
                signal = imu[ch_idx] - np.mean(imu[ch_idx])
                if ch_name not in features[label]:
                    features[label][ch_name] = {"peak": [], "rms": [], "range": []}
                features[label].setdefault(ch_name, {"peak": [], "rms": [], "range": []})
                features[label][ch_name]["peak"].append(np.max(np.abs(signal)))
                features[label][ch_name]["rms"].append(np.sqrt(np.mean(signal ** 2)))
                features[label][ch_name]["range"].append(np.ptp(signal))

    # Print comparison table
    print(f"\n  {'Channel':12s} {'Feature':8s} | {'nod_yes':>10s} {'nod_no':>10s} {'still':>10s} | {'yes/still':>10s} {'no/still':>10s}")
    print(f"  {'-'*12} {'-'*8} | {'-'*10} {'-'*10} {'-'*10} | {'-'*10} {'-'*10}")

    best_features = []
    for ch_name in CH_NAMES:
        for feat_name in ["peak", "rms", "range"]:
            vals = {}
            for label in ["nod_yes", "nod_no", "still"]:
                if ch_name in features[label] and feat_name in features[label][ch_name]:
                    vals[label] = np.median(features[label][ch_name][feat_name])
                else:
                    vals[label] = 0

            if vals["still"] > 0:
                ratio_yes = vals["nod_yes"] / vals["still"]
                ratio_no = vals["nod_no"] / vals["still"]
            else:
                ratio_yes = ratio_no = float('inf')

            print(f"  {ch_name:12s} {feat_name:8s} | {vals['nod_yes']:10.2f} {vals['nod_no']:10.2f} {vals['still']:10.2f} | {ratio_yes:10.1f}x {ratio_no:10.1f}x")

            # Track features that discriminate yes from no
            if vals["nod_yes"] > 0 and vals["nod_no"] > 0:
                separation = max(vals["nod_yes"], vals["nod_no"]) / min(vals["nod_yes"], vals["nod_no"])
                best_features.append((separation, ch_name, feat_name, vals))

    best_features.sort(reverse=True)
    print(f"\n  Top discriminating features (nod_yes vs nod_no):")
    for sep, ch, feat, vals in best_features[:5]:
        direction = "yes>no" if vals["nod_yes"] > vals["nod_no"] else "no>yes"
        print(f"    {ch}.{feat}: {sep:.1f}x separation ({direction})")


def suggest_thresholds(nod_yes, nod_no, still):
    """Suggest detection thresholds based on data."""
    print(f"\n{'='*70}")
    print("THRESHOLD SUGGESTIONS")
    print(f"{'='*70}")

    # Gyro pitch (ch4) for nod_yes
    yes_pitch_peaks = []
    no_pitch_peaks = []
    still_pitch_peaks = []

    for trial in nod_yes:
        signal = trial["imu"][4] - np.mean(trial["imu"][4])
        yes_pitch_peaks.append(np.max(np.abs(signal)))
    for trial in nod_no:
        signal = trial["imu"][4] - np.mean(trial["imu"][4])
        no_pitch_peaks.append(np.max(np.abs(signal)))
    for trial in still:
        signal = trial["imu"][4] - np.mean(trial["imu"][4])
        still_pitch_peaks.append(np.max(np.abs(signal)))

    yes_pitch_peaks = np.array(yes_pitch_peaks)
    no_pitch_peaks = np.array(no_pitch_peaks)
    still_pitch_peaks = np.array(still_pitch_peaks)

    print(f"\n  gyro_pitch (nod yes detector):")
    print(f"    nod_yes peaks: min={yes_pitch_peaks.min():.1f}  p5={np.percentile(yes_pitch_peaks,5):.1f}  median={np.median(yes_pitch_peaks):.1f}")
    print(f"    nod_no  peaks: min={no_pitch_peaks.min():.1f}  p5={np.percentile(no_pitch_peaks,5):.1f}  median={np.median(no_pitch_peaks):.1f}")
    print(f"    still   peaks: min={still_pitch_peaks.min():.1f}  p95={np.percentile(still_pitch_peaks,95):.1f}  max={still_pitch_peaks.max():.1f}")

    # Find threshold that separates yes+still with best accuracy
    for thresh in [5, 10, 15, 20, 30, 40, 50, 75, 100]:
        yes_tp = np.sum(yes_pitch_peaks > thresh)
        no_fp = np.sum(no_pitch_peaks > thresh)
        still_fp = np.sum(still_pitch_peaks > thresh)
        print(f"    threshold={thresh:3d} deg/s: yes_detect={yes_tp}/{len(yes_pitch_peaks)}  no_fp={no_fp}/{len(no_pitch_peaks)}  still_fp={still_fp}/{len(still_pitch_peaks)}")

    # Gyro yaw (ch5) for nod_no
    yes_yaw_peaks = []
    no_yaw_peaks = []
    still_yaw_peaks = []

    for trial in nod_yes:
        signal = trial["imu"][5] - np.mean(trial["imu"][5])
        yes_yaw_peaks.append(np.max(np.abs(signal)))
    for trial in nod_no:
        signal = trial["imu"][5] - np.mean(trial["imu"][5])
        no_yaw_peaks.append(np.max(np.abs(signal)))
    for trial in still:
        signal = trial["imu"][5] - np.mean(trial["imu"][5])
        still_yaw_peaks.append(np.max(np.abs(signal)))

    yes_yaw_peaks = np.array(yes_yaw_peaks)
    no_yaw_peaks = np.array(no_yaw_peaks)
    still_yaw_peaks = np.array(still_yaw_peaks)

    print(f"\n  gyro_yaw (head shake / nod no detector):")
    print(f"    nod_yes peaks: min={yes_yaw_peaks.min():.1f}  median={np.median(yes_yaw_peaks):.1f}  max={yes_yaw_peaks.max():.1f}")
    print(f"    nod_no  peaks: min={no_yaw_peaks.min():.1f}  p5={np.percentile(no_yaw_peaks,5):.1f}  median={np.median(no_yaw_peaks):.1f}")
    print(f"    still   peaks: min={still_yaw_peaks.min():.1f}  p95={np.percentile(still_yaw_peaks,95):.1f}  max={still_yaw_peaks.max():.1f}")

    for thresh in [5, 10, 15, 20, 30, 40, 50, 75, 100]:
        no_tp = np.sum(no_yaw_peaks > thresh)
        yes_fp = np.sum(yes_yaw_peaks > thresh)
        still_fp = np.sum(still_yaw_peaks > thresh)
        print(f"    threshold={thresh:3d} deg/s: no_detect={no_tp}/{len(no_yaw_peaks)}  yes_fp={yes_fp}/{len(yes_yaw_peaks)}  still_fp={still_fp}/{len(still_yaw_peaks)}")


def main():
    print("Loading IMU recordings...")
    nod_yes = load_imu_trials("nod_yes")
    nod_no = load_imu_trials("nod_no")
    still = load_imu_trials("head_still")

    print(f"  nod_yes={len(nod_yes)}, nod_no={len(nod_no)}, head_still={len(still)}")

    analyze_channel_stats("nod_yes", nod_yes)
    analyze_channel_stats("nod_no", nod_no)
    analyze_channel_stats("head_still", still)

    if nod_yes and nod_no and still:
        find_discriminating_features(nod_yes, nod_no, still)
        suggest_thresholds(nod_yes, nod_no, still)


if __name__ == "__main__":
    main()
