"""Validate ConcentrationScorer output on existing recordings.

Checks that the BrainFlow MINDFULNESS/RESTFULNESS models produce
usable 0-1 scores that differentiate between mental states.

Usage: PYTHONPATH=. python scripts/validate_concentration.py
"""
import glob

import numpy as np
from brainflow.data_filter import DataFilter, DetrendOperations, WindowOperations
from brainflow.ml_model import MLModel, BrainFlowModelParams, BrainFlowMetrics, BrainFlowClassifiers

from backend.pipeline.stages.features import BandPowerExtractor, BandPowerResult
from backend.pipeline.types import PipelineFrame


def get_concentration_scores(eeg: np.ndarray, sfreq: int = 256) -> list[tuple[float, float]]:
    """Compute (concentration, relaxation) for each 2s window."""
    window = sfreq * 2
    step = sfreq // 2

    extractor = BandPowerExtractor()

    mind_params = BrainFlowModelParams(BrainFlowMetrics.MINDFULNESS, BrainFlowClassifiers.DEFAULT_CLASSIFIER)
    rest_params = BrainFlowModelParams(BrainFlowMetrics.RESTFULNESS, BrainFlowClassifiers.DEFAULT_CLASSIFIER)
    mindfulness = MLModel(mind_params)
    restfulness = MLModel(rest_params)
    try:
        mindfulness.release()
    except Exception:
        pass
    mindfulness.prepare()
    try:
        restfulness.release()
    except Exception:
        pass
    restfulness.prepare()

    scores = []
    try:
        for start in range(0, eeg.shape[1] - window, step):
            chunk = eeg[:, start:start + window]
            frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=0.0)
            extractor.process(frame)
            bp = frame.get(BandPowerResult)
            if bp is None:
                continue

            band_names_ordered = ["delta", "theta", "alpha", "beta", "gamma"]
            total = 0.0
            sums = []
            for b in band_names_ordered:
                s = sum(bp.band_powers.get(b, [0.0]))
                sums.append(s)
                total += s
            if total <= 0:
                continue
            features = np.array([s / total for s in sums], dtype=np.float64)

            conc = float(mindfulness.predict(features))
            relax = float(restfulness.predict(features))
            scores.append((conc, relax))
    finally:
        mindfulness.release()
        restfulness.release()

    return scores


def load_recordings(label: str) -> list[np.ndarray]:
    files = sorted(glob.glob(f"recordings/{label}/**/*.npz", recursive=True))
    return [np.load(f, allow_pickle=True)["eeg"] for f in files]


def main():
    print("=" * 60)
    print("ConcentrationScorer Validation")
    print("=" * 60)

    labels = ["rest", "meditation", "mental_math", "eyes_closed", "eyes_open"]
    results = {}

    for label in labels:
        recordings = load_recordings(label)
        if not recordings:
            print(f"  {label}: no recordings found")
            continue
        all_scores = []
        for rec in recordings:
            all_scores.extend(get_concentration_scores(rec))
        if not all_scores:
            print(f"  {label}: no valid windows")
            continue
        concs = [s[0] for s in all_scores]
        relax = [s[1] for s in all_scores]
        results[label] = {"conc": concs, "relax": relax}
        print(f"\n  {label} ({len(recordings)} recordings, {len(all_scores)} windows):")
        print(f"    concentration: mean={np.mean(concs):.3f}, std={np.std(concs):.3f}, "
              f"min={np.min(concs):.3f}, max={np.max(concs):.3f}")
        print(f"    relaxation:    mean={np.mean(relax):.3f}, std={np.std(relax):.3f}, "
              f"min={np.min(relax):.3f}, max={np.max(relax):.3f}")

    # Key comparison: mental_math vs rest
    print("\n" + "=" * 60)
    print("State Separation Analysis")
    print("=" * 60)

    if "mental_math" in results and "rest" in results:
        math_conc = results["mental_math"]["conc"]
        rest_conc = results["rest"]["conc"]
        math_mean = np.mean(math_conc)
        rest_mean = np.mean(rest_conc)
        delta = math_mean - rest_mean

        # Cohen's d
        pooled_std = np.sqrt((np.std(math_conc)**2 + np.std(rest_conc)**2) / 2)
        d = delta / pooled_std if pooled_std > 0 else 0

        print(f"\n  mental_math concentration: mean={math_mean:.3f}")
        print(f"  rest concentration:        mean={rest_mean:.3f}")
        print(f"  Delta: {delta:+.3f}")
        print(f"  Cohen's d: {d:.2f}")

        if d > 0.5:
            print("  GOOD: meaningful separation (d > 0.5)")
        elif d > 0.2:
            print("  WEAK: small separation (0.2 < d < 0.5) — may need tuning")
        else:
            print("  POOR: negligible separation (d < 0.2) — fallback to raw theta/beta needed")

    if "meditation" in results and "rest" in results:
        med_relax = results["meditation"]["relax"]
        rest_relax = results["rest"]["relax"]
        med_mean = np.mean(med_relax)
        rest_mean_r = np.mean(rest_relax)
        delta_r = med_mean - rest_mean_r
        pooled_std_r = np.sqrt((np.std(med_relax)**2 + np.std(rest_relax)**2) / 2)
        d_r = delta_r / pooled_std_r if pooled_std_r > 0 else 0

        print(f"\n  meditation relaxation: mean={med_mean:.3f}")
        print(f"  rest relaxation:      mean={rest_mean_r:.3f}")
        print(f"  Delta: {delta_r:+.3f}")
        print(f"  Cohen's d: {d_r:.2f}")

    # Also check raw theta/beta as fallback
    print("\n" + "=" * 60)
    print("Raw Theta/Beta Ratio (Fallback)")
    print("=" * 60)

    for label in ["rest", "mental_math", "meditation"]:
        recordings = load_recordings(label)
        if not recordings:
            continue
        ratios = []
        extractor = BandPowerExtractor()
        for rec in recordings:
            for start in range(0, rec.shape[1] - 512, 128):
                chunk = rec[:, start:start + 512]
                frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=0.0)
                extractor.process(frame)
                bp = frame.get(BandPowerResult)
                if bp and bp.theta_beta_ratio:
                    # Frontal channels (AF7=1, AF8=2)
                    frontal_ratio = (bp.theta_beta_ratio[1] + bp.theta_beta_ratio[2]) / 2
                    ratios.append(frontal_ratio)
        if ratios:
            print(f"  {label:15s}: theta/beta mean={np.mean(ratios):.2f}, std={np.std(ratios):.2f}")


if __name__ == "__main__":
    main()
