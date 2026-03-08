import math
import numpy as np
from brainflow.data_filter import DataFilter

CH_NAMES = ["TP9", "AF7", "AF8", "TP10"]
BAND_NAMES = ["delta", "theta", "alpha", "beta", "gamma"]

BANDS = {
    "delta": (0.5, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (8.0, 13.0),
    "beta": (13.0, 30.0),
    "gamma": (30.0, 45.0),
}

GRAVITY = 9.81
RAIL_THRESHOLD = 995.0


def compute_band_powers(
    eeg: np.ndarray, sampling_rate: int = 256
) -> dict[str, list[float]]:
    """Compute average band powers per channel.
    Args:
        eeg: (n_channels, n_samples) array
        sampling_rate: Hz
    Returns:
        Dict with band names as keys, lists of per-channel power as values.
    """
    result = {band: [] for band in BAND_NAMES}
    for ch_idx in range(eeg.shape[0]):
        channel_data = eeg[ch_idx].copy()
        try:
            psd = DataFilter.get_psd_welch(
                channel_data,
                256,  # nfft
                256 // 2,  # overlap
                sampling_rate,
                2,  # hamming window
            )
            bands = DataFilter.get_avg_band_powers(psd)
            for i, band_name in enumerate(BAND_NAMES):
                result[band_name].append(float(bands[0][i]))
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
    """Compute head movement magnitude from accelerometer.
    Returns deviation of accel vector from gravity (0 = still).
    """
    mean_accel = np.mean(accel, axis=1)
    magnitude = float(np.linalg.norm(mean_accel))
    deviation = abs(magnitude - GRAVITY) / GRAVITY
    return round(deviation, 3)


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

    if eeg is not None and eeg.shape[1] >= 256:
        band_powers = compute_band_powers(eeg, sampling_rate)
        quality = compute_signal_quality(eeg)
        metrics["eeg"] = {
            "band_powers": band_powers,
            "theta_beta_ratio": compute_theta_beta_ratio(band_powers),
            "frontal_alpha_asymmetry": compute_frontal_alpha_asymmetry(band_powers),
            "signal_quality": quality,
            "fit_status": compute_fit_status(quality),
        }

    if ppg is not None and ppg.shape[1] >= 64:
        try:
            hr = float(DataFilter.get_heart_rate(ppg[0], 64, 64, 3))
        except Exception:
            hr = 0.0
        try:
            spo2 = float(DataFilter.get_oxygen_level(ppg[:2], 64, 10))
        except Exception:
            spo2 = 0.0
        metrics["ppg"] = {
            "heart_rate_bpm": round(hr, 1),
            "spo2_percent": round(spo2, 1),
            "hrv_rmssd_ms": 0.0,
        }

    if imu is not None and imu.shape[1] > 0:
        accel = imu[:3]
        movement = compute_head_movement(accel)
        pitch, roll = compute_head_pose(accel)
        metrics["imu"] = {
            "head_movement": movement,
            "head_pose": {"pitch": pitch, "roll": roll},
            "motion_artifact": movement > 0.3,
            "jaw_clench": False,
        }

    return metrics
