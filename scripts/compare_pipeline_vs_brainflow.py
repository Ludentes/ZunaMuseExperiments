"""Compare our pipeline implementation vs BrainFlow built-in alternatives.

Tests on recorded experiment data (rest, single_blink, double_blink).
Comparisons:
1. BandPassFilter vs WaveletDenoiser — SNR improvement
2. Our BandPowerExtractor vs get_custom_band_powers — value agreement
3. detect_peaks_z_score for blink detection — precision/recall on labeled data
4. MLModel(MINDFULNESS/RESTFULNESS) — does it work on Muse 4ch?
"""
import glob
import numpy as np
from pathlib import Path
from brainflow.data_filter import (
    DataFilter, DetrendOperations, WindowOperations,
    NoiseTypes, WaveletTypes, FilterTypes,
)
from brainflow.ml_model import MLModel, BrainFlowMetrics, BrainFlowClassifiers

# Our pipeline
from backend.pipeline.types import PipelineFrame, Cadence, BANDS, BAND_NAMES
from backend.pipeline.stages.preprocessing import BandPassFilter, WaveletDenoiser
from backend.pipeline.stages.features import BandPowerExtractor, BandPowerResult


def load_trials(label: str, max_trials: int = 20) -> list[np.ndarray]:
    """Load EEG arrays from recordings/<label>/."""
    pattern = f"recordings/{label}/{label}_t*.npz"
    files = sorted(glob.glob(pattern))[:max_trials]
    trials = []
    for f in files:
        data = np.load(f)
        eeg = data["eeg"]
        if eeg.size and eeg.ndim == 2:
            trials.append(eeg.astype(np.float64))
    return trials


def snr_db(signal: np.ndarray, noise: np.ndarray) -> float:
    """Signal-to-noise ratio in dB."""
    s_power = np.mean(signal ** 2)
    n_power = np.mean(noise ** 2)
    if n_power == 0:
        return float("inf")
    return 10 * np.log10(s_power / n_power)


# ============================================================
# 1. BandPassFilter vs WaveletDenoiser
# ============================================================
def compare_preprocessing(trials: list[np.ndarray], label: str):
    print(f"\n{'='*60}")
    print(f"1. PREPROCESSING: BandPass vs Wavelet ({label}, {len(trials)} trials)")
    print(f"{'='*60}")

    bandpass = BandPassFilter(lowcut=1.0, highcut=45.0)
    wavelet = WaveletDenoiser()

    bp_snrs = []
    wv_snrs = []

    for eeg in trials:
        if eeg.shape[1] < 64:
            continue

        # BandPass
        frame_bp = PipelineFrame(eeg=eeg.copy(), ppg=None, imu=None, timestamp=0.0)
        bandpass.process(frame_bp)
        from backend.pipeline.stages.preprocessing import PreprocessingResult
        bp_result = frame_bp.get(PreprocessingResult)

        # Wavelet
        frame_wv = PipelineFrame(eeg=eeg.copy(), ppg=None, imu=None, timestamp=0.0)
        wavelet.process(frame_wv)
        wv_result = frame_wv.get(PreprocessingResult)

        if bp_result and wv_result:
            # SNR: filtered signal vs removed noise
            for ch in range(eeg.shape[0]):
                bp_noise = eeg[ch] - bp_result.eeg_filtered[ch]
                wv_noise = eeg[ch] - wv_result.eeg_filtered[ch]
                bp_snrs.append(snr_db(bp_result.eeg_filtered[ch], bp_noise))
                wv_snrs.append(snr_db(wv_result.eeg_filtered[ch], wv_noise))

    if bp_snrs:
        print(f"  BandPass SNR: {np.mean(bp_snrs):.1f} ± {np.std(bp_snrs):.1f} dB")
        print(f"  Wavelet  SNR: {np.mean(wv_snrs):.1f} ± {np.std(wv_snrs):.1f} dB")
        diff = np.mean(wv_snrs) - np.mean(bp_snrs)
        winner = "Wavelet" if diff > 0 else "BandPass"
        print(f"  → {winner} wins by {abs(diff):.1f} dB")
    else:
        print("  No valid trials")


# ============================================================
# 2. Our BandPowerExtractor vs get_custom_band_powers
# ============================================================
def compare_band_powers(trials: list[np.ndarray], label: str):
    print(f"\n{'='*60}")
    print(f"2. BAND POWERS: Our PSD loop vs get_custom_band_powers ({label})")
    print(f"{'='*60}")

    extractor = BandPowerExtractor()
    band_ranges = list(BANDS.values())

    diffs = {b: [] for b in BAND_NAMES}

    for eeg in trials:
        if eeg.shape[1] < 256:
            continue

        # Our method
        frame = PipelineFrame(eeg=eeg.copy(), ppg=None, imu=None, timestamp=0.0)
        extractor.process(frame)
        our_result = frame.get(BandPowerResult)
        if not our_result:
            continue

        # BrainFlow's get_custom_band_powers (operates on full 2D array)
        try:
            channels = list(range(eeg.shape[0]))
            bf_powers, _ = DataFilter.get_custom_band_powers(
                eeg.astype(np.float64).copy(), band_ranges, channels, 256, True,
            )
            # bf_powers are normalized (relative), our values are absolute µV²
            # Compare relative distribution instead
            our_total = sum(
                sum(our_result.band_powers[b]) for b in BAND_NAMES
            )
            for bi, band_name in enumerate(BAND_NAMES):
                our_sum = sum(our_result.band_powers[band_name])
                our_rel = our_sum / our_total if our_total > 0 else 0
                bf_rel = bf_powers[bi]
                if our_rel > 0 and bf_rel > 0:
                    rel_diff = abs(our_rel - bf_rel) / max(our_rel, bf_rel)
                    diffs[band_name].append(rel_diff)
        except Exception as e:
            print(f"  BrainFlow error: {e}")

    print("  Band       Our mean    BF mean    Rel.Diff")
    print("  " + "-" * 48)
    for band_name in BAND_NAMES:
        if diffs[band_name]:
            mean_diff = np.mean(diffs[band_name])
            print(f"  {band_name:<10} {'—':>10} {'—':>10}    {mean_diff:.3f}")
        else:
            print(f"  {band_name:<10} no data")


# ============================================================
# 3. Blink detection: detect_peaks_z_score on labeled data
# ============================================================
def compare_blink_detection(rest_trials: list[np.ndarray], blink_trials: list[np.ndarray]):
    print(f"\n{'='*60}")
    print(f"3. BLINK DETECTION: detect_peaks_z_score precision/recall")
    print(f"   rest={len(rest_trials)} trials, blink={len(blink_trials)} trials")
    print(f"{'='*60}")

    thresholds = [2.5, 3.0, 3.5, 4.0, 5.0]

    for z_thresh in thresholds:
        true_pos = 0  # blink trial with detection
        false_neg = 0  # blink trial with no detection
        true_neg = 0   # rest trial with no detection
        false_pos = 0  # rest trial with detection

        for eeg in blink_trials:
            if eeg.shape[1] < 32:
                continue
            # Use AF7+AF8 average (frontal channels)
            frontal = ((eeg[1] + eeg[2]) / 2.0).astype(np.float64)
            try:
                peaks = DataFilter.detect_peaks_z_score(
                    frontal, lag=30, threshold=z_thresh, influence=0.3,
                )
                if np.any(peaks != 0):
                    true_pos += 1
                else:
                    false_neg += 1
            except Exception:
                false_neg += 1

        for eeg in rest_trials:
            if eeg.shape[1] < 32:
                continue
            frontal = ((eeg[1] + eeg[2]) / 2.0).astype(np.float64)
            try:
                peaks = DataFilter.detect_peaks_z_score(
                    frontal, lag=30, threshold=z_thresh, influence=0.3,
                )
                if np.any(peaks != 0):
                    false_pos += 1
                else:
                    true_neg += 1
            except Exception:
                true_neg += 1

        precision = true_pos / (true_pos + false_pos) if (true_pos + false_pos) > 0 else 0
        recall = true_pos / (true_pos + false_neg) if (true_pos + false_neg) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

        print(f"  z={z_thresh:.1f}  TP={true_pos:2d} FP={false_pos:2d} "
              f"FN={false_neg:2d} TN={true_neg:2d}  "
              f"P={precision:.2f} R={recall:.2f} F1={f1:.2f}")


# ============================================================
# 4. BrainFlow MLModel (MINDFULNESS / RESTFULNESS)
# ============================================================
def test_ml_models(rest_trials: list[np.ndarray], blink_trials: list[np.ndarray]):
    print(f"\n{'='*60}")
    print(f"4. BRAINFLOW ML MODELS: Mindfulness/Restfulness on Muse 4ch")
    print(f"{'='*60}")

    for model_type, model_name in [
        (BrainFlowMetrics.MINDFULNESS, "Mindfulness"),
        (BrainFlowMetrics.RESTFULNESS, "Restfulness"),
    ]:
        try:
            from brainflow.ml_model import BrainFlowModelParams
            params = BrainFlowModelParams(model_type, BrainFlowClassifiers.DEFAULT_CLASSIFIER)
            model = MLModel(params)
            model.prepare()

            rest_scores = []
            blink_scores = []

            band_ranges = list(BANDS.values())
            channels = [0, 1, 2, 3]

            for eeg in rest_trials:
                if eeg.shape[1] < 256:
                    continue
                try:
                    powers, _ = DataFilter.get_custom_band_powers(
                        eeg.astype(np.float64).copy(), band_ranges, channels, 256, True,
                    )
                    score = model.predict(powers)
                    rest_scores.append(score)
                except Exception as e:
                    print(f"  {model_name} predict error: {e}")

            for eeg in blink_trials:
                if eeg.shape[1] < 256:
                    continue
                try:
                    powers, _ = DataFilter.get_custom_band_powers(
                        eeg.astype(np.float64).copy(), band_ranges, channels, 256, True,
                    )
                    score = model.predict(powers)
                    blink_scores.append(score)
                except Exception as e:
                    print(f"  {model_name} predict error: {e}")

            model.release()

            if rest_scores:
                print(f"\n  {model_name}:")
                print(f"    Rest trials:  {np.mean(rest_scores):.3f} ± {np.std(rest_scores):.3f} "
                      f"(range {np.min(rest_scores):.3f} — {np.max(rest_scores):.3f})")
            if blink_scores:
                print(f"    Blink trials: {np.mean(blink_scores):.3f} ± {np.std(blink_scores):.3f} "
                      f"(range {np.min(blink_scores):.3f} — {np.max(blink_scores):.3f})")
            if rest_scores and blink_scores:
                sep = abs(np.mean(rest_scores) - np.mean(blink_scores))
                print(f"    Separation: {sep:.3f} — {'usable' if sep > 0.1 else 'NOT separable'}")

        except Exception as e:
            print(f"  {model_name}: FAILED — {e}")


# ============================================================
# 5. Wavelet denoising quality on blink trials
# ============================================================
def compare_denoising_blink_preservation(blink_trials: list[np.ndarray]):
    print(f"\n{'='*60}")
    print(f"5. DENOISING: Does wavelet preserve blink shape better?")
    print(f"{'='*60}")

    bandpass = BandPassFilter(lowcut=1.0, highcut=45.0)
    wavelet = WaveletDenoiser()

    bp_peak_preserved = []
    wv_peak_preserved = []

    for eeg in blink_trials:
        if eeg.shape[1] < 64:
            continue

        # Find peak amplitude in raw frontal channels
        raw_frontal = (eeg[1] + eeg[2]) / 2.0
        raw_peak = np.min(raw_frontal)  # blinks are negative deflections

        from backend.pipeline.stages.preprocessing import PreprocessingResult

        # BandPass
        frame_bp = PipelineFrame(eeg=eeg.copy(), ppg=None, imu=None, timestamp=0.0)
        bandpass.process(frame_bp)
        bp_r = frame_bp.get(PreprocessingResult)

        # Wavelet
        frame_wv = PipelineFrame(eeg=eeg.copy(), ppg=None, imu=None, timestamp=0.0)
        wavelet.process(frame_wv)
        wv_r = frame_wv.get(PreprocessingResult)

        if bp_r and wv_r:
            bp_frontal = (bp_r.eeg_filtered[1] + bp_r.eeg_filtered[2]) / 2.0
            wv_frontal = (wv_r.eeg_filtered[1] + wv_r.eeg_filtered[2]) / 2.0

            bp_peak = np.min(bp_frontal)
            wv_peak = np.min(wv_frontal)

            # How much of the blink peak amplitude is preserved (ratio)
            if raw_peak != 0:
                bp_peak_preserved.append(bp_peak / raw_peak)
                wv_peak_preserved.append(wv_peak / raw_peak)

    if bp_peak_preserved:
        print(f"  BandPass peak preservation: {np.mean(bp_peak_preserved):.2f} ± {np.std(bp_peak_preserved):.2f}")
        print(f"  Wavelet  peak preservation: {np.mean(wv_peak_preserved):.2f} ± {np.std(wv_peak_preserved):.2f}")
        print(f"  (1.0 = perfect preservation, <1.0 = attenuated)")
        bp_mean = np.mean(bp_peak_preserved)
        wv_mean = np.mean(wv_peak_preserved)
        winner = "Wavelet" if wv_mean > bp_mean else "BandPass"
        print(f"  → {winner} preserves blink shape better")
    else:
        print("  No valid trials")


def main():
    print("Loading recorded trials...")
    rest = load_trials("rest")
    single_blink = load_trials("single_blink")
    double_blink = load_trials("double_blink")
    print(f"  rest: {len(rest)}, single_blink: {len(single_blink)}, double_blink: {len(double_blink)}")

    # 1. Preprocessing comparison (on rest — cleanest signal)
    compare_preprocessing(rest, "rest")
    compare_preprocessing(single_blink, "single_blink")

    # 2. Band power agreement
    compare_band_powers(rest, "rest")

    # 3. Blink detection
    compare_blink_detection(rest, single_blink)

    # 4. ML models
    test_ml_models(rest, single_blink)

    # 5. Blink preservation
    compare_denoising_blink_preservation(single_blink)

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print("See above for detailed results. Key questions answered:")
    print("  1. BandPass vs Wavelet: which gives better SNR?")
    print("  2. Our band powers vs BrainFlow's: do they agree?")
    print("  3. detect_peaks_z_score: what threshold gives best F1 for blinks?")
    print("  4. MLModel: does it produce useful scores on Muse 4ch?")
    print("  5. Which denoiser preserves blink shape better?")


if __name__ == "__main__":
    main()
