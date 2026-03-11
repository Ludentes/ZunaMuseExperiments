from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from brainflow.data_filter import DataFilter, DetrendOperations, WindowOperations

from backend.pipeline.base import Stage
from backend.pipeline.stages.preprocessing import PreprocessingResult
from backend.pipeline.types import BANDS, BAND_NAMES, CH_NAMES, Cadence, PipelineFrame

# Channel names for FAA: AF7 (left frontal), AF8 (right frontal)
_FAA_LEFT = "AF7"
_FAA_RIGHT = "AF8"


RAIL_THRESHOLD = 995.0  # µV


@dataclass
class BandPowerResult:
    band_powers: dict[str, list[float]]
    theta_beta_ratio: list[float]
    frontal_alpha_asymmetry: float


@dataclass
class SignalQualityResult:
    quality: dict[str, float]
    fit_status: str


@dataclass
class HeartRateResult:
    heart_rate_bpm: float
    spo2_percent: float
    hrv_rmssd_ms: float


@dataclass
class HeadMotionResult:
    head_movement: float
    head_pose: tuple[float, float]
    motion_artifact: bool


@dataclass
class EyesClosedResult:
    eyes_closed: bool
    alpha_ratio: float      # current frontal alpha / baseline
    baseline_alpha: float   # current baseline value


class EyesClosedDetector(Stage):
    """Detect eyes-closed state via sustained frontal alpha power increase.

    Uses frontal channels (AF7 + AF8) alpha power from BandPowerResult.
    Maintains a slow-adapting baseline and detects when alpha exceeds
    the baseline by a configurable multiplier for a sustained duration.

    Hysteresis: once eyes_closed is True, alpha must drop below a lower
    threshold (open_threshold) to transition back to eyes_open.

    Must run AFTER BandPowerExtractor in the SLOW pipeline.
    """

    name = "eyes_closed_detector"
    cadence = Cadence.SLOW

    def __init__(
        self,
        close_threshold: float = 2.0,
        open_threshold: float = 1.3,
        sustain_seconds: float = 1.5,
        baseline_ema_alpha: float = 0.002,
        cold_start_ticks: int = 6,
    ):
        self.close_threshold = close_threshold
        self.open_threshold = open_threshold
        self.sustain_seconds = sustain_seconds
        self._baseline_ema_alpha = baseline_ema_alpha
        self._cold_start_ticks = cold_start_ticks

        self._baseline: float = 0.0
        self._tick_count: int = 0
        self._eyes_closed: bool = False
        self._high_since: float = 0.0

    def process(self, frame: PipelineFrame) -> None:
        bp = frame.get(BandPowerResult)
        if bp is None or "alpha" not in bp.band_powers:
            return

        alpha_list = bp.band_powers["alpha"]

        # Find AF7/AF8 indices by channel name
        ch_names = list(CH_NAMES)
        if len(alpha_list) > len(CH_NAMES):
            from backend.pipeline.stages.zuna import ZUNA_CH_NAMES
            ch_names = ZUNA_CH_NAMES
        af7_idx = ch_names.index("AF7") if "AF7" in ch_names else 1
        af8_idx = ch_names.index("AF8") if "AF8" in ch_names else 2

        if af7_idx >= len(alpha_list) or af8_idx >= len(alpha_list):
            return

        frontal_alpha = (alpha_list[af7_idx] + alpha_list[af8_idx]) / 2.0
        self._tick_count += 1

        # Baseline update
        if self._tick_count <= self._cold_start_ticks:
            self._baseline = (
                self._baseline * (self._tick_count - 1) + frontal_alpha
            ) / self._tick_count
        elif not self._eyes_closed:
            self._baseline = (
                self._baseline_ema_alpha * frontal_alpha
                + (1 - self._baseline_ema_alpha) * self._baseline
            )

        # Don't detect during cold start
        if self._tick_count < self._cold_start_ticks:
            frame.set(EyesClosedResult(
                eyes_closed=False,
                alpha_ratio=0.0,
                baseline_alpha=self._baseline,
            ))
            return

        ratio = frontal_alpha / self._baseline if self._baseline > 0 else 0.0
        now = frame.timestamp

        if not self._eyes_closed:
            if ratio >= self.close_threshold:
                if self._high_since == 0.0:
                    self._high_since = now
                elif now - self._high_since >= self.sustain_seconds:
                    self._eyes_closed = True
            else:
                self._high_since = 0.0
        else:
            if ratio < self.open_threshold:
                self._eyes_closed = False
                self._high_since = 0.0

        frame.set(EyesClosedResult(
            eyes_closed=self._eyes_closed,
            alpha_ratio=round(ratio, 2),
            baseline_alpha=round(self._baseline, 2),
        ))


class BandPowerExtractor(Stage):
    name = "band_power_extractor"
    cadence = Cadence.SLOW

    def __init__(self, bands: dict[str, tuple[float, float]] | None = None):
        self.bands = bands or BANDS

    def _get_channel_names(self, n_channels: int) -> list[str]:
        """Return channel names matching the current EEG layout."""
        if n_channels <= len(CH_NAMES):
            return list(CH_NAMES[:n_channels])
        # 23ch ZUNA mode
        from backend.pipeline.stages.zuna import ZUNA_CH_NAMES
        return ZUNA_CH_NAMES[:n_channels]

    def process(self, frame: PipelineFrame) -> None:
        # Use ZUNA 23ch output if available, else fall back to preprocessed/raw 4ch
        from backend.pipeline.stages.zuna import ZunaResult
        zuna = frame.get(ZunaResult)
        if zuna is not None:
            eeg = zuna.eeg_23ch
        else:
            prep = frame.get(PreprocessingResult)
            eeg = prep.eeg_filtered if prep else frame.eeg
        if eeg is None:
            return

        sampling_rate = 256
        nfft = DataFilter.get_nearest_power_of_two(sampling_rate)
        if eeg.shape[1] < nfft:
            return

        n_channels = eeg.shape[0]
        ch_names = self._get_channel_names(n_channels)
        band_powers: dict[str, list[float]] = {b: [] for b in BAND_NAMES}

        for ch_idx in range(n_channels):
            channel_data = eeg[ch_idx].astype(np.float64).copy()
            try:
                # Winsorize: clip to ±4 SD to prevent spikes from dominating PSD
                mu = np.mean(channel_data)
                sd = np.std(channel_data)
                if sd > 0:
                    np.clip(channel_data, mu - 4 * sd, mu + 4 * sd, out=channel_data)
                DataFilter.detrend(channel_data, DetrendOperations.LINEAR.value)
                psd = DataFilter.get_psd_welch(
                    channel_data, nfft, nfft // 2,
                    sampling_rate, WindowOperations.HANNING.value,
                )
                for band_name in BAND_NAMES:
                    low, high = self.bands[band_name]
                    power = DataFilter.get_band_power(psd, low, high)
                    band_powers[band_name].append(round(float(power), 2))
            except Exception:
                for band_name in BAND_NAMES:
                    band_powers[band_name].append(0.0)

        # Theta/beta ratio
        theta_beta = []
        for i in range(len(band_powers.get("theta", []))):
            theta = band_powers["theta"][i]
            beta = band_powers["beta"][i]
            theta_beta.append(round(theta / beta, 2) if beta > 0 else 0.0)

        # Frontal alpha asymmetry — find AF7/AF8 by name, not hardcoded index
        faa = 0.0
        alpha = band_powers.get("alpha", [])
        af7_idx = ch_names.index(_FAA_LEFT) if _FAA_LEFT in ch_names else -1
        af8_idx = ch_names.index(_FAA_RIGHT) if _FAA_RIGHT in ch_names else -1
        if af7_idx >= 0 and af8_idx >= 0 and af7_idx < len(alpha) and af8_idx < len(alpha):
            af7_alpha = max(alpha[af7_idx], 1e-10)
            af8_alpha = max(alpha[af8_idx], 1e-10)
            faa = round(math.log(af8_alpha) - math.log(af7_alpha), 3)

        frame.set(BandPowerResult(
            band_powers=band_powers,
            theta_beta_ratio=theta_beta,
            frontal_alpha_asymmetry=faa,
        ))


class SignalQualityChecker(Stage):
    name = "signal_quality_checker"
    cadence = Cadence.SLOW

    def _get_channel_names(self, n_channels: int) -> list[str]:
        """Return channel names matching the current EEG layout."""
        if n_channels <= len(CH_NAMES):
            return list(CH_NAMES[:n_channels])
        from backend.pipeline.stages.zuna import ZUNA_CH_NAMES
        return ZUNA_CH_NAMES[:n_channels]

    def process(self, frame: PipelineFrame) -> None:
        if frame.eeg is None or frame.eeg.shape[1] == 0:
            return

        ch_names = self._get_channel_names(frame.eeg.shape[0])
        quality = {}
        for i, name in enumerate(ch_names):
            channel = frame.eeg[i]
            n = len(channel)
            railed = float(np.sum(np.abs(channel) > RAIL_THRESHOLD)) / n
            railed_score = max(0.0, 1.0 - railed * 10)
            std = float(np.std(channel))
            if std < 2.0:
                std_score = 0.2
            elif std > 200.0:
                std_score = 0.3
            else:
                std_score = 1.0
            quality[name] = round(min(railed_score, std_score), 2)

        poor_count = sum(1 for q in quality.values() if q < 0.7)
        if poor_count == 0:
            fit = "good"
        elif poor_count <= 2:
            fit = "adjust"
        else:
            fit = "poor"

        frame.set(SignalQualityResult(quality=quality, fit_status=fit))


class HeartRateExtractor(Stage):
    name = "heart_rate_extractor"
    cadence = Cadence.SLOW

    def __init__(self):
        self._ppg_accumulator: np.ndarray | None = None
        self._max_samples = 1280  # 20s at 64Hz

    def process(self, frame: PipelineFrame) -> None:
        if frame.ppg is None:
            return

        # Accumulate PPG across ticks
        if self._ppg_accumulator is not None:
            self._ppg_accumulator = np.concatenate(
                [self._ppg_accumulator, frame.ppg], axis=1
            )
        else:
            self._ppg_accumulator = frame.ppg.copy()

        if self._ppg_accumulator.shape[1] > self._max_samples:
            self._ppg_accumulator = self._ppg_accumulator[:, -self._max_samples:]

        if self._ppg_accumulator.shape[1] < 1024:
            return

        ppg = self._ppg_accumulator
        ppg_ir = ppg[1].astype(np.float64)
        ppg_red = ppg[0].astype(np.float64)

        try:
            hr = float(DataFilter.get_heart_rate(ppg_ir, ppg_red, 64, 1024))
        except Exception:
            hr = 0.0

        try:
            spo2 = float(DataFilter.get_oxygen_level(ppg_ir, ppg_red, 64))
        except Exception:
            spo2 = 0.0

        # HRV RMSSD from peak detection
        hrv_rmssd = 0.0
        try:
            ppg_filt = ppg_ir.copy()
            DataFilter.detrend(ppg_filt, DetrendOperations.LINEAR.value)
            DataFilter.perform_bandpass(ppg_filt, 64, 0.5, 4.0, 4, 0, 0.0)
            diff = np.diff(ppg_filt)
            peaks = []
            for i in range(1, len(diff)):
                if diff[i - 1] > 0 and diff[i] <= 0:
                    peaks.append(i)
            if len(peaks) >= 3:
                rr_intervals = np.diff(peaks) / 64.0 * 1000.0
                rr_intervals = rr_intervals[(rr_intervals > 300) & (rr_intervals < 2000)]
                if len(rr_intervals) >= 2:
                    successive_diffs = np.diff(rr_intervals)
                    hrv_rmssd = float(np.sqrt(np.mean(successive_diffs ** 2)))
        except Exception:
            hrv_rmssd = 0.0

        frame.set(HeartRateResult(
            heart_rate_bpm=round(hr, 1),
            spo2_percent=round(spo2, 1),
            hrv_rmssd_ms=round(hrv_rmssd, 1),
        ))


class HeadMotionExtractor(Stage):
    name = "head_motion_extractor"
    cadence = Cadence.SLOW

    def process(self, frame: PipelineFrame) -> None:
        if frame.imu is None or frame.imu.shape[1] < 2:
            return

        accel = frame.imu[:3]

        # Movement: RMS of per-axis std-dev
        std_per_axis = np.std(accel, axis=1)
        movement = round(float(np.sqrt(np.mean(std_per_axis ** 2))), 4)

        # Pose: pitch/roll from mean accel
        mean_accel = np.mean(accel, axis=1)
        ax, ay, az = float(mean_accel[0]), float(mean_accel[1]), float(mean_accel[2])
        pitch = round(math.degrees(math.atan2(ax, math.sqrt(ay**2 + az**2))), 1)
        roll = round(math.degrees(math.atan2(ay, math.sqrt(ax**2 + az**2))), 1)

        frame.set(HeadMotionResult(
            head_movement=movement,
            head_pose=(pitch, roll),
            motion_artifact=movement > 0.05,
        ))


@dataclass
class ConcentrationResult:
    concentration_score: float   # 0.0 - 1.0
    relaxation_score: float      # 0.0 - 1.0 (from RESTFULNESS model)


class ConcentrationScorer(Stage):
    name = "concentration_scorer"
    cadence = Cadence.SLOW

    def __init__(self, use_raw_ratio: bool = True):
        """
        Args:
            use_raw_ratio: If True, use frontal theta/beta ratio for concentration
                          instead of BrainFlow MINDFULNESS model (which gives inverted results).
                          RESTFULNESS model is always used for relaxation.
        """
        self.use_raw_ratio = use_raw_ratio
        from brainflow.ml_model import MLModel, BrainFlowModelParams, BrainFlowMetrics, BrainFlowClassifiers

        if not use_raw_ratio:
            mind_params = BrainFlowModelParams(BrainFlowMetrics.MINDFULNESS, BrainFlowClassifiers.DEFAULT_CLASSIFIER)
            self._mindfulness = MLModel(mind_params)
            try:
                self._mindfulness.release()
            except Exception:
                pass
            self._mindfulness.prepare()
        else:
            self._mindfulness = None

        rest_params = BrainFlowModelParams(BrainFlowMetrics.RESTFULNESS, BrainFlowClassifiers.DEFAULT_CLASSIFIER)
        self._restfulness = MLModel(rest_params)
        try:
            self._restfulness.release()
        except Exception:
            pass
        self._restfulness.prepare()

    def release(self):
        """Release BrainFlow ML models (call on shutdown)."""
        if self._mindfulness:
            try:
                self._mindfulness.release()
            except Exception:
                pass
        try:
            self._restfulness.release()
        except Exception:
            pass

    def process(self, frame: PipelineFrame) -> None:
        bp = frame.get(BandPowerResult)
        if bp is None:
            return

        # --- Concentration ---
        if self.use_raw_ratio:
            # Use frontal theta/beta ratio directly
            # Find AF7/AF8 indices
            ch_names = list(CH_NAMES)
            n_channels = len(bp.band_powers.get("theta", []))
            if n_channels > len(CH_NAMES):
                from backend.pipeline.stages.zuna import ZUNA_CH_NAMES
                ch_names = ZUNA_CH_NAMES
            af7_idx = ch_names.index("AF7") if "AF7" in ch_names else 1
            af8_idx = ch_names.index("AF8") if "AF8" in ch_names else 2

            theta = bp.band_powers.get("theta", [0.0] * 4)
            beta = bp.band_powers.get("beta", [0.0] * 4)

            if af7_idx < len(theta) and af8_idx < len(theta):
                frontal_theta = (theta[af7_idx] + theta[af8_idx]) / 2
                frontal_beta = (beta[af7_idx] + beta[af8_idx]) / 2
                raw_ratio = frontal_theta / frontal_beta if frontal_beta > 0 else 5.0
            else:
                raw_ratio = 2.5  # neutral default

            # Map ratio to 0-1: high ratio = relaxed (high theta), low ratio = focused (high beta)
            # Typical observed range: ~1.0 (focused) to ~5.0 (relaxed)
            # Invert so concentration=1.0 when focused (low ratio)
            concentration = max(0.0, min(1.0, 1.0 - (raw_ratio - 1.0) / 4.0))
        else:
            # BrainFlow MINDFULNESS model (known to give inverted results)
            band_names_ordered = ["delta", "theta", "alpha", "beta", "gamma"]
            total = 0.0
            sums = []
            for b in band_names_ordered:
                s = sum(bp.band_powers.get(b, [0.0]))
                sums.append(s)
                total += s
            if total <= 0:
                return
            features = np.array([s / total for s in sums], dtype=np.float64)
            try:
                result = self._mindfulness.predict(features)
                concentration = float(result.item() if hasattr(result, 'item') else result)
            except Exception:
                concentration = 0.0

        # --- Relaxation (RESTFULNESS model always) ---
        band_names_ordered = ["delta", "theta", "alpha", "beta", "gamma"]
        total = 0.0
        sums = []
        for b in band_names_ordered:
            s = sum(bp.band_powers.get(b, [0.0]))
            sums.append(s)
            total += s
        if total <= 0:
            return
        features = np.array([s / total for s in sums], dtype=np.float64)
        try:
            result = self._restfulness.predict(features)
            relaxation = float(result.item() if hasattr(result, 'item') else result)
        except Exception:
            relaxation = 0.0

        frame.set(ConcentrationResult(
            concentration_score=round(concentration, 3),
            relaxation_score=round(relaxation, 3),
        ))
