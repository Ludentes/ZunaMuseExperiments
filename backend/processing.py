import math
import numpy as np
from brainflow.data_filter import DataFilter, DetrendOperations, WindowOperations

CH_NAMES = ["TP9", "AF7", "AF8", "TP10"]
BAND_NAMES = ["delta", "theta", "alpha", "beta", "gamma"]

BANDS = {
    "delta": (0.5, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (8.0, 13.0),
    "beta": (13.0, 30.0),
    "gamma": (30.0, 45.0),
}

GRAVITY = 1.0  # Muse 2 accelerometer reports in g's
RAIL_THRESHOLD = 995.0  # µV


def compute_band_powers(
    eeg: np.ndarray, sampling_rate: int = 256
) -> dict[str, list[float]]:
    """Compute band powers per channel using BrainFlow's get_band_power.

    Args:
        eeg: (n_channels, n_samples) array in µV
        sampling_rate: Hz
    Returns:
        Dict with band names as keys, lists of per-channel power as values.
    """
    nfft = DataFilter.get_nearest_power_of_two(sampling_rate)
    result = {band: [] for band in BAND_NAMES}

    for ch_idx in range(eeg.shape[0]):
        channel_data = eeg[ch_idx].astype(np.float64)
        n = len(channel_data)
        if n < nfft:
            for band_name in BAND_NAMES:
                result[band_name].append(0.0)
            continue
        try:
            DataFilter.detrend(channel_data, DetrendOperations.LINEAR.value)
            psd = DataFilter.get_psd_welch(
                channel_data, nfft, nfft // 2,
                sampling_rate, WindowOperations.HANNING.value,
            )
            for band_name in BAND_NAMES:
                low, high = BANDS[band_name]
                power = DataFilter.get_band_power(psd, low, high)
                result[band_name].append(round(float(power), 2))
        except Exception:
            for band_name in BAND_NAMES:
                result[band_name].append(0.0)
    return result


def compute_signal_quality(eeg: np.ndarray) -> dict[str, float]:
    """Compute 0-1 signal quality score per channel."""
    quality = {}
    for i, name in enumerate(CH_NAMES[: eeg.shape[0]]):
        channel = eeg[i]
        n = len(channel)
        if n == 0:
            quality[name] = 0.0
            continue
        railed = np.sum(np.abs(channel) > RAIL_THRESHOLD) / n
        railed_score = max(0.0, 1.0 - railed * 10)
        std = float(np.std(channel))
        if std < 2.0:
            std_score = 0.2
        elif std > 200.0:
            std_score = 0.3
        else:
            std_score = 1.0
        quality[name] = round(min(railed_score, std_score), 2)
    return quality


def compute_fit_status(quality: dict[str, float]) -> str:
    """Determine overall headband fit from per-channel quality scores."""
    poor_count = sum(1 for q in quality.values() if q < 0.7)
    if poor_count == 0:
        return "good"
    elif poor_count <= 2:
        return "adjust"
    else:
        return "poor"


def compute_theta_beta_ratio(band_powers: dict[str, list[float]]) -> list[float]:
    """Compute theta/beta ratio per channel. Higher = less focused."""
    ratios = []
    for i in range(len(band_powers.get("theta", []))):
        theta = band_powers["theta"][i]
        beta = band_powers["beta"][i]
        ratios.append(round(theta / beta, 2) if beta > 0 else 0.0)
    return ratios


def compute_frontal_alpha_asymmetry(band_powers: dict[str, list[float]]) -> float:
    """Compute FAA = log(alpha_AF8) - log(alpha_AF7).
    Positive = more left-frontal alpha = approach/positive valence.
    """
    alpha = band_powers.get("alpha", [0, 0, 0, 0])
    if len(alpha) < 4:
        return 0.0
    af7_alpha = max(alpha[1], 1e-10)
    af8_alpha = max(alpha[2], 1e-10)
    return round(math.log(af8_alpha) - math.log(af7_alpha), 3)


def compute_head_movement(accel: np.ndarray) -> float:
    """Compute head movement from accelerometer variance.
    Uses per-sample acceleration magnitude variance over the window.
    Returns RMS of per-axis std-dev (0 = perfectly still).
    """
    if accel.shape[1] < 2:
        return 0.0
    # Standard deviation of each axis over the time window
    std_per_axis = np.std(accel, axis=1)  # shape (3,)
    # RMS of the three axis stdevs — captures jitter in any direction
    rms_std = float(np.sqrt(np.mean(std_per_axis**2)))
    return round(rms_std, 4)


def compute_head_pose(accel: np.ndarray) -> tuple[float, float]:
    """Compute pitch and roll from accelerometer (degrees)."""
    mean_accel = np.mean(accel, axis=1)
    ax, ay, az = float(mean_accel[0]), float(mean_accel[1]), float(mean_accel[2])
    pitch = math.degrees(math.atan2(ax, math.sqrt(ay**2 + az**2)))
    roll = math.degrees(math.atan2(ay, math.sqrt(ax**2 + az**2)))
    return round(pitch, 1), round(roll, 1)


def build_metrics(
    eeg: np.ndarray | None,
    ppg: np.ndarray | None,
    imu: np.ndarray | None,
    sampling_rate: int = 256,
) -> dict:
    """Build the full metrics JSON payload from sensor data."""
    metrics: dict = {}

    # Need at least nfft samples for PSD (256 for 256Hz → nfft=256)
    nfft = DataFilter.get_nearest_power_of_two(sampling_rate)
    if eeg is not None and eeg.shape[1] >= nfft:
        band_powers = compute_band_powers(eeg, sampling_rate)
        quality = compute_signal_quality(eeg)
        metrics["eeg"] = {
            "band_powers": band_powers,
            "theta_beta_ratio": compute_theta_beta_ratio(band_powers),
            "frontal_alpha_asymmetry": compute_frontal_alpha_asymmetry(band_powers),
            "signal_quality": quality,
            "fit_status": compute_fit_status(quality),
        }

    # PPG: channels are [Red=0, IR=1, Ambient=2] per BrainFlow Muse 2 docs
    if ppg is not None and ppg.shape[1] >= 1024:
        ppg_ir = ppg[1].astype(np.float64)    # channel index 1 = IR
        ppg_red = ppg[0].astype(np.float64)   # channel index 0 = Red
        try:
            hr = float(DataFilter.get_heart_rate(ppg_ir, ppg_red, 64, 1024))
        except Exception as e:
            import logging
            logging.getLogger("eeg-server").warning("get_heart_rate failed: %s", e)
            hr = 0.0
        try:
            spo2 = float(DataFilter.get_oxygen_level(ppg_ir, ppg_red, 64))
        except Exception as e:
            import logging
            logging.getLogger("eeg-server").warning("get_oxygen_level failed: %s", e)
            spo2 = 0.0

        # HRV: compute RMSSD from R-R intervals detected in IR PPG signal
        hrv_rmssd = 0.0
        try:
            # Detect peaks in IR PPG for R-R intervals
            ppg_ir_filtered = ppg_ir.copy()
            DataFilter.detrend(ppg_ir_filtered, DetrendOperations.LINEAR.value)
            DataFilter.perform_bandpass(ppg_ir_filtered, 64, 0.5, 4.0, 4,
                                        0, 0.0)  # 0.5-4Hz bandpass for pulse
            # Simple peak detection via zero-crossings of derivative
            diff = np.diff(ppg_ir_filtered)
            peaks = []
            for i in range(1, len(diff)):
                if diff[i - 1] > 0 and diff[i] <= 0:
                    peaks.append(i)
            if len(peaks) >= 3:
                rr_intervals = np.diff(peaks) / 64.0 * 1000.0  # ms
                # Filter physiological range (300-2000ms = 30-200 bpm)
                rr_intervals = rr_intervals[
                    (rr_intervals > 300) & (rr_intervals < 2000)
                ]
                if len(rr_intervals) >= 2:
                    successive_diffs = np.diff(rr_intervals)
                    hrv_rmssd = float(
                        np.sqrt(np.mean(successive_diffs ** 2))
                    )
        except Exception:
            hrv_rmssd = 0.0

        metrics["ppg"] = {
            "heart_rate_bpm": round(hr, 1),
            "spo2_percent": round(spo2, 1),
            "hrv_rmssd_ms": round(hrv_rmssd, 1),
        }

    if imu is not None and imu.shape[1] > 0:
        accel = imu[:3]
        movement = compute_head_movement(accel)
        pitch, roll = compute_head_pose(accel)
        metrics["imu"] = {
            "head_movement": movement,
            "head_pose": {"pitch": pitch, "roll": roll},
            "motion_artifact": movement > 0.05,
            "jaw_clench": False,
        }

    return metrics
